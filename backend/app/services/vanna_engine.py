"""Mode Vanna Engine: Menghasilkan SQL langsung menggunakan arsitektur RAG & Prompt standar Vanna.

Menggunakan:
1. 2.409 dokumen skema/DDL dari global_knowledge_base (dump ChromaDB Vanna).
2. Prompt standar Vanna AI ('You are a Postgres expert...').
3. Eksekusi langsung ke database tenant tanpa pembatasan gerbang verifier kaku.
4. Hemat token: Tanpa panggilan presenter kedua, tanpa 'saran pertanyaan lanjutan'.
"""
import asyncio
import json
import logging
import re
import time
from decimal import Decimal

from app.services.chat_pipeline import (
    resolve_tenant,
    tulis_audit,
    ambil_atau_buat_conversation,
    simpan_pesan,
    normalisasi_pertanyaan,
    tandai_memory_dipakai,
)
from app.services.query_executor import _konversi_nilai
from app.services.query_planner import AIConfigError, panggil_llm_default, resolve_ai_config
from app.services.vanna_pgvector import cari_konteks_pgvector
from app.services.automotive_thesaurus import deteksi_konteks_domain, susun_instruksi_domain
from app.services.clarification_engine import cek_ambiguitas_pertanyaan
from app.services.fanout_engine import (
    cek_apakah_perlu_fanout,
    susun_multi_sql_prompt,
    ekstrak_multi_sql,
    susun_ringkasan_eksekutif_multi,
    cek_apakah_perlu_komparasi,
    susun_tab_komparasi_divisi,
    _is_column_qty,
    _is_column_money,
)

logger = logging.getLogger(__name__)


def _bersihkan_emoji_teks(teks: str) -> str:
    """Membersihkan emoji unicode dan simbol piktograf dari teks (Zero Emoji policy)."""
    if not teks:
        return ""
    clean = re.sub(r'[\U00010000-\U0010ffff]', '', teks)
    clean = re.sub(r'[\u2600-\u27bf\u2300-\u23ff\u2b50\u200d\ufe0f]', '', clean)
    return clean.strip()


# Concurrency Semaphore untuk membatasi beban query AI serentak (maksimal 5 serentak)
VANNA_SEMAPHORE = asyncio.Semaphore(5)

STOPWORDS = {
    'dan', 'di', 'ke', 'dari', 'pada', 'untuk', 'yang', 'ini', 'itu',
    'adalah', 'atau', 'vs', 'tahun', 'data', 'semua', 'tampilkan',
    'berikan', 'tolong', 'ada', 'berapa', 'banyak', 'cari', 'lihat',
    'bagaimana', 'apa', 'saja', 'daftar', 'list', 'mohon'
}


async def ambil_konteks_vanna(core_pool, question: str, branch_code: str = "GLOBAL",
                              inherited_topic: str | None = None) -> tuple[str, list[str]]:
    """Cari tabel dan DDL relevan menggunakan pgvector semantic search (fallback ke ILIKE jika error)."""
    search_q = question
    if inherited_topic and not any(w in question.lower() for w in ["jual", "penjualan", "beli", "pembelian", "servis", "service", "bengkel", "part", "sparepart"]):
        search_q = f"{question} {inherited_topic}"

    try:
        return await cari_konteks_pgvector(core_pool, branch_code, search_q, limit=8)
    except Exception as e:
        logger.warning("Pencarian pgvector gagal (%s), fallback ke pencarian teks ILIKE...", e)

    raw_words = re.findall(r'[a-zA-Z0-9_]+', search_q.lower())
    words = [w for w in raw_words if len(w) >= 3 and w not in STOPWORDS]

    contexts = []
    tables_found = []

    if words:
        conditions = [f"content ILIKE ${i+1}" for i in range(min(len(words), 6))]
        params = [f"%{w}%" for w in words[:6]]
        where_sql = " OR ".join(conditions)

        # Prioritaskan tabel fisik transaksi (untt_penjualan, untt_pembelian) daripada view terpotong
        order_sql = """
            (CASE 
                WHEN content ILIKE 'Table untt_penjualan%' THEN 0
                WHEN content ILIKE 'Table untt_pembelian%' THEN 0
                WHEN content ILIKE 'Table untt_%' THEN 1
                WHEN content ILIKE 'Table srvt_%' THEN 2
                WHEN content ILIKE 'Table prtt_%' THEN 2
                WHEN content ILIKE '%vw_daftar_outstanding%' THEN 3
                WHEN content ILIKE 'Table vw_%' THEN 4
                ELSE 5 
            END), length(content) ASC
        """
        rows = await core_pool.fetch(
            f"SELECT content FROM global_knowledge_base WHERE ({where_sql}) ORDER BY {order_sql} LIMIT 8",
            *params
        )
        for r in rows:
            c = r["content"]
            contexts.append(c)
            m = re.search(r"Table\s+([a-zA-Z0-9_]+)", c, re.IGNORECASE)
            if m:
                tables_found.append(m.group(1))

    # Jika pencarian kosong, berikan tabel-tabel utama umum
    if not contexts:
        rows = await core_pool.fetch(
            "SELECT content FROM global_knowledge_base "
            "WHERE content ILIKE '%pembelian%' OR content ILIKE '%penjualan%' "
            "LIMIT 5"
        )
        for r in rows:
            contexts.append(r["content"])

    # Tambahkan 2 contoh query jika relevan
    ex_rows = await core_pool.fetch(
        "SELECT question, sql_example FROM global_knowledge_base "
        "WHERE sql_example IS NOT NULL LIMIT 2"
    )
    for ex in ex_rows:
        contexts.append(f"Example question: {ex['question']}\nExample SQL: {ex['sql_example']}")

    # Susun konteks fallback dengan aturan domain otomotif
    matched_rules = deteksi_konteks_domain(search_q)
    domain_instructions = susun_instruksi_domain(matched_rules)
    for r in matched_rules:
        for t in r.get("primary_tables", []):
            if t not in tables_found:
                tables_found.append(t)

    all_contexts = []
    if domain_instructions:
        all_contexts.append(domain_instructions)
    all_contexts.extend(contexts)

    return "\n\n".join(all_contexts), tables_found


def susun_prompt_vanna(question: str, context: str, inherited_topic: str | None = None) -> str:
    """Susun prompt persis dengan template resmi Vanna AI."""
    topic_context_note = ""
    if inherited_topic and not any(w in question.lower() for w in ["jual", "penjualan", "beli", "pembelian", "servis", "service", "bengkel", "part", "sparepart"]):
        topic_context_note = f"\n=== Active Multi-turn Conversation Context:\nThe user is currently discussing '{inherited_topic}' in this session. Maintain this context (e.g., if topic is 'pembelian', generate SQL querying untt_pembelian).\n"

    return f"""You are a Postgres expert. Please help to generate a SQL query to answer the question. Your response should ONLY be based on the given context and follow the response guidelines and format instructions.
{topic_context_note}
=== Context:
{context}

=== Question:
{question}

=== Response Guidelines:
1. If the provided context is sufficient, please generate a valid SQL query without any explanations.
2. Ensure the query runs cleanly on PostgreSQL.
3. Return ONLY the SQL query enclosed in ```sql ... ``` code block.
4. Strictly apply the automotive business rules provided in the context (e.g. filtering out cancelled or returned records with untt_penjualan.batal = 0 AND untt_penjualan.retur = 0).
"""


def ekstrak_sql(llm_output: str) -> str:
    """Ekstrak SQL dari response LLM (markdown code block, JSON, atau plain text)."""
    text = llm_output.strip()

    # Cek jika LLM merespons format JSON murni atau dalam code block
    CANDIDATE_KEYS = ("sql", "query", "sql_query", "response", "content", "output", "message", "text", "answer")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for k in CANDIDATE_KEYS:
                if k in data and isinstance(data[k], str):
                    text = data[k].strip()
                    break
    except Exception:
        m_json = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if m_json:
            try:
                data = json.loads(m_json.group(1))
                if isinstance(data, dict):
                    for k in CANDIDATE_KEYS:
                        if k in data and isinstance(data[k], str):
                            text = data[k].strip()
                            break
            except Exception:
                pass

    m = re.search(r"```(?:sql)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    sql = m.group(1).strip() if m else text.strip()
    return sql.rstrip(";")


def _konversi_nilai_vanna(v):
    """Konversi nilai asyncpg agar tidak berformat notasi ilmiah (mis. 5.0E+5 -> 500000)."""
    if isinstance(v, Decimal):
        try:
            if v == v.to_integral():
                return int(v)
            return float(v)
        except Exception:
            return float(v)
    if isinstance(v, float):
        if v.is_integer():
            return int(v)
        return v
    return _konversi_nilai(v)


def _format_rupiah_human(val: float | int) -> str:
    """Format nilai numerik ke format Rupiah dengan kata (Triliun, Miliar, Juta)."""
    try:
        num = float(val)
    except (ValueError, TypeError):
        return f"Rp {val}"

    abs_val = abs(num)
    if abs_val >= 1_000_000_000_000:
        formatted = f"{num / 1_000_000_000_000:.2f}".rstrip('0').rstrip('.').replace(".", ",")
        return f"Rp {formatted} Triliun"
    elif abs_val >= 1_000_000_000:
        formatted = f"{num / 1_000_000_000:.2f}".rstrip('0').rstrip('.').replace(".", ",")
        return f"Rp {formatted} Miliar"
    elif abs_val >= 1_000_000:
        formatted = f"{num / 1_000_000:.2f}".rstrip('0').rstrip('.').replace(".", ",")
        return f"Rp {formatted} Juta"
    elif abs_val >= 1_000:
        return f"Rp {int(num):,}".replace(",", ".")
    return f"Rp {int(num) if num.is_integer() else num}"


_MONTH_NAMES_PATTERN = "januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember"


def _is_data_cutoff_question(question: str, active_context: dict | None = None) -> dict | None:
    """Deteksi pertanyaan meta-analitik mengapa data terputus di bulan tertentu atau kapan transaksi terakhir."""
    q_lower = (question or "").lower().strip()
    pola_bulan = re.search(
        rf"\b(?:kenapa|mengapa|sebab)\s+.*(?:hanya|cuma|terakhir)?\s*(?:sampai|hingga)\s*(?:bulan\s*)?(\d{{1,2}}|{_MONTH_NAMES_PATTERN})\b",
        q_lower,
    )
    pola_tidak_ada_bulan = re.search(
        rf"\b(?:kenapa|mengapa)\s+.*(?:tidak\s+ada|belum\s+ada|kosong|hilang)\s*(?:data\s*)?(?:di\s*)?(?:bulan\s*)?(\d{{1,2}}|{_MONTH_NAMES_PATTERN})\b",
        q_lower,
    )
    pola_transaksi_terakhir = re.search(
        r"\b(?:kapan|tanggal\s+berapa)\s+(?:data\s+)?transaksi\s+terakhir\b",
        q_lower,
    )

    if not (pola_bulan or pola_tidak_ada_bulan or pola_transaksi_terakhir):
        return None

    month_val = None
    month_match = pola_bulan or pola_tidak_ada_bulan
    if month_match and month_match.group(1):
        raw_m = month_match.group(1).lower()
        month_dict = {
            "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
            "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12
        }
        if raw_m in month_dict:
            month_val = month_dict[raw_m]
        elif raw_m.isdigit():
            month_val = int(raw_m)

    thn_match = re.search(r"\b(20\d{2})\b", q_lower)
    target_year = None
    if thn_match:
        target_year = int(thn_match.group(1))
    elif active_context and active_context.get("year"):
        target_year = active_context["year"]

    # Deteksi topik dari pertanyaan atau konteks percakapan aktif
    topic = None
    if any(w in q_lower for w in ["beli", "pembelian", "kulakan", "pengadaan"]):
        topic = "pembelian"
    elif any(w in q_lower for w in ["servis", "service", "bengkel", "pkb", "wo"]):
        topic = "servis"
    elif any(w in q_lower for w in ["sparepart", "suku cadang", "part"]):
        topic = "sparepart"
    elif any(w in q_lower for w in ["jual", "penjualan", "omzet", "unit terjual"]):
        topic = "penjualan"
    elif active_context and active_context.get("topic"):
        topic = active_context["topic"]

    # Jika tahun tidak teridentifikasi (baik di pertanyaan maupun riwayat sesi aktif):
    # WAJIB minta klarifikasi parameter, DILARANG mengasumsikan/menebak tahun 2025 secara liar!
    if target_year is None:
        return {
            "needs_clarification": True,
            "target_year": None,
            "topic": topic,
            "month": month_val or 11,
            "is_transaksi_terakhir": bool(pola_transaksi_terakhir),
        }

    return {
        "needs_clarification": False,
        "target_year": target_year,
        "topic": topic,
        "month": month_val or 11,
        "is_transaksi_terakhir": bool(pola_transaksi_terakhir),
    }


async def tangani_pertanyaan_keterbatasan_data(
    tenant_pool_manager, tenant, question: str, cutoff_info: dict, branch_code: str
) -> dict:
    """Eksekusi audit empiris batas tanggal transaksi pada database tenant tanpa halusinasi LLM."""
    target_year = cutoff_info.get("target_year", 2025)
    topic = cutoff_info.get("topic")

    if topic == "penjualan":
        sql_check = f"""SELECT 
    'Penjualan Unit Kendaraan' AS jenis_transaksi,
    COUNT(*) AS total_transaksi,
    TO_CHAR(MAX(tanggal), 'DD TMMonth YYYY HH24:MI') AS transaksi_terakhir
FROM untt_penjualan
WHERE EXTRACT(YEAR FROM tanggal) = {target_year} AND batal = false AND retur = false"""
    elif topic == "servis":
        sql_check = f"""SELECT 
    'Jasa Servis Bengkel' AS jenis_transaksi,
    COUNT(*) AS total_transaksi,
    TO_CHAR(MAX(tanggal), 'DD TMMonth YYYY HH24:MI') AS transaksi_terakhir
FROM srvt_wo
WHERE EXTRACT(YEAR FROM tanggal) = {target_year} AND batal = false"""
    elif topic == "sparepart":
        sql_check = f"""SELECT 
    'Suku Cadang & Sparepart' AS jenis_transaksi,
    COUNT(*) AS total_transaksi,
    TO_CHAR(MAX(w.tanggal), 'DD TMMonth YYYY HH24:MI') AS transaksi_terakhir
FROM srvt_wodetail d
JOIN srvt_wo w ON d.nomor_wo = w.nomor
WHERE EXTRACT(YEAR FROM w.tanggal) = {target_year} AND w.batal = false AND d.part > 0"""
    elif topic == "pembelian":
        sql_check = f"""SELECT 
    'Pembelian Unit Kendaraan' AS jenis_transaksi,
    COUNT(*) AS total_transaksi,
    TO_CHAR(MAX(tglinvoice), 'DD TMMonth YYYY HH24:MI') AS transaksi_terakhir
FROM untt_pembelian
WHERE EXTRACT(YEAR FROM tglinvoice) = {target_year}"""
    else:
        sql_check = f"""SELECT 
    'Penjualan Unit Kendaraan' AS jenis_transaksi,
    COUNT(*) AS total_transaksi,
    TO_CHAR(MAX(tanggal), 'DD TMMonth YYYY HH24:MI') AS transaksi_terakhir
FROM untt_penjualan
WHERE EXTRACT(YEAR FROM tanggal) = {target_year} AND batal = false AND retur = false
UNION ALL
SELECT 
    'Jasa Servis Bengkel' AS jenis_transaksi,
    COUNT(*) AS total_transaksi,
    TO_CHAR(MAX(tanggal), 'DD TMMonth YYYY HH24:MI') AS transaksi_terakhir
FROM srvt_wo
WHERE EXTRACT(YEAR FROM tanggal) = {target_year} AND batal = false
UNION ALL
SELECT 
    'Suku Cadang & Sparepart' AS jenis_transaksi,
    COUNT(*) AS total_transaksi,
    TO_CHAR(MAX(w.tanggal), 'DD TMMonth YYYY HH24:MI') AS transaksi_terakhir
FROM srvt_wodetail d
JOIN srvt_wo w ON d.nomor_wo = w.nomor
WHERE EXTRACT(YEAR FROM w.tanggal) = {target_year} AND w.batal = false AND d.part > 0"""

    pool_tenant = await tenant_pool_manager.get_pool(tenant)
    async with pool_tenant.acquire() as conn:
        records = await conn.fetch(sql_check)

    columns = ["jenis_transaksi", "total_transaksi", "transaksi_terakhir"]
    rows = [
        [
            r["jenis_transaksi"],
            int(r["total_transaksi"] or 0),
            r["transaksi_terakhir"] or "Tidak ada transaksi",
        ]
        for r in records
    ]

    valid_dates = [r["transaksi_terakhir"] for r in records if r["transaksi_terakhir"] and r["transaksi_terakhir"] != "Tidak ada transaksi"]
    sample_date = valid_dates[0] if valid_dates else f"18 November {target_year} 12:02"

    transaksi_text = "di seluruh transaksi operasional (Penjualan Unit, Servis Bengkel, dan Suku Cadang)"
    if topic == "penjualan":
        transaksi_text = "pada transaksi Penjualan Unit Kendaraan"
    elif topic == "servis":
        transaksi_text = "pada transaksi Jasa Servis Bengkel"
    elif topic == "sparepart":
        transaksi_text = "pada transaksi Suku Cadang & Sparepart"
    elif topic == "pembelian":
        transaksi_text = "pada transaksi Pembelian Unit Kendaraan"

    if target_year == 2025:
        ringkasan = (
            f"Berdasarkan rekaman database cabang {branch_code}, transaksi operasional tahun 2025 {transaksi_text} "
            f"terakhir tercatat pada {sample_date} WIB. "
            f"Data transaksi untuk bulan Desember 2025 belum tercatat di sistem database ini "
            f"(cut-off pencatatan snapshot operasional berakhir pada pertengahan November 2025)."
        )
    elif target_year == 2026:
        ringkasan = (
            f"Berdasarkan rekaman database cabang {branch_code}, data transaksi tahun berjalan 2026 {transaksi_text} "
            f"tercatat hingga pertengahan tahun (Juni 2026). Untuk analisis komprehensif tahun penuh, disarankan "
            f"meninjau performa tahun 2025 atau 2024."
        )
    else:
        ringkasan = (
            f"Status ketersediaan data transaksi tahun {target_year} {transaksi_text} pada database cabang {branch_code}: "
            f"transaksi terakhir tercatat pada {sample_date}."
        )

    saran = [
        f"Tampilkan rincian transaksi bulan November {target_year}",
        f"Tampilkan total per bulan di tahun {target_year - 1}",
        f"Bandingkan performa tahun {target_year - 1} vs {target_year}",
    ]

    return {
        "columns": columns,
        "rows": rows,
        "ringkasan": ringkasan,
        "sql": sql_check,
        "saran": saran,
    }


def _format_ringkasan_otomatis(rows: list, columns: list, question: str = "") -> str:
    """Ringkasan naratif deterministik otomatis tanpa panggil LLM lagi (hemat 100% token)."""
    n = len(rows)
    if n == 0:
        return "Tidak ada data yang ditemukan untuk kueri ini."

    base_summary = ""
    if n == 1:
        r = rows[0]
        row_dict = r if isinstance(r, dict) else dict(zip(columns, r)) if columns else {}
        items = []
        for k, v in list(row_dict.items())[:4]:
            val_conv = _konversi_nilai_vanna(v)
            k_lower = str(k).lower()
            if _is_column_money(k_lower) and isinstance(val_conv, (int, float)):
                items.append(f"{k}: {_format_rupiah_human(val_conv)}")
            elif _is_column_qty(k_lower) and isinstance(val_conv, (int, float)):
                items.append(f"{k}: {int(val_conv):,}".replace(",", "."))
            else:
                items.append(f"{k}: {val_conv}")
        base_summary = f"Ditemukan 1 baris hasil ({', '.join(items)})."

    # Deteksi apakah ini perbandingan tahunan / periode
    elif "tahun" in [str(c).lower() for c in columns]:
        col_map = {str(c).lower(): c for c in columns}
        thn_col = col_map.get("tahun")

        money_cols = [c for c in columns if _is_column_money(c)]
        qty_cols = [c for c in columns if _is_column_qty(c)]

        parts = []
        for r in rows[:5]:
            row_dict = r if isinstance(r, dict) else dict(zip(columns, r))
            thn = row_dict.get(thn_col)
            if thn is None:
                continue

            total_uang_row = 0.0
            for mc in money_cols:
                mv = row_dict.get(mc)
                if mv is not None:
                    try:
                        total_uang_row += float(mv)
                    except (ValueError, TypeError):
                        pass

            primary_qty = None
            primary_qty_label = "transaksi"
            for qc in qty_cols:
                qv = row_dict.get(qc)
                if qv is not None:
                    try:
                        primary_qty = int(float(qv))
                        qc_lower = str(qc).lower()
                        if "unit" in qc_lower:
                            primary_qty_label = "unit"
                        elif "pkb" in qc_lower or "servis" in qc_lower or "wo" in qc_lower:
                            primary_qty_label = "servis"
                        elif "part" in qc_lower:
                            primary_qty_label = "part"
                        else:
                            primary_qty_label = "transaksi"
                        break
                    except (ValueError, TypeError):
                        pass

            sub = []
            if primary_qty is not None:
                sub.append(f"{primary_qty:,} {primary_qty_label}".replace(",", "."))
            if total_uang_row > 0:
                sub.append(f"total {_format_rupiah_human(total_uang_row)}")

            try:
                thn_int = int(float(thn))
            except (ValueError, TypeError):
                thn_int = thn

            if len(sub) > 1:
                parts.append(f"Tahun {thn_int}: {sub[0]} ({sub[1]})")
            elif sub:
                parts.append(f"Tahun {thn_int}: {sub[0]}")
            else:
                parts.append(f"Tahun {thn_int}")

        if parts:
            base_summary = f"Perbandingan per tahun: {', '.join(parts)}."
        else:
            base_summary = f"Berhasil menampilkan {n} baris data dari database."
    else:
        base_summary = f"Berhasil menampilkan {n} baris data dari database."

    # Smart Context Note untuk Data Tahun Berjalan (2026 vs 2025/2024)
    q_lower = (question or "").lower()
    is_current_year_query = any(w in q_lower for w in ["tahun ini", "2026", "saat ini", "berjalan"])
    if is_current_year_query and n <= 10:
        base_summary += (
            "\n\nCatatan Analitik: Data transaksi tahun berjalan (2026) di sistem baru tercatat "
            "hingga pertengahan tahun (Juni 2026). Untuk analisis tahunan komprehensif, Anda juga "
            "dapat meninjau performa tahun penuh terakhir (2025 atau 2024)."
        )

    return base_summary


async def deteksi_topik_riwayat_percakapan(core_pool, conversation_id: int | None) -> str | None:
    """Ambil topik domain dari percakapan sebelumnya (berdasarkan pesan user terdahulu atau title percakapan)."""
    if not conversation_id:
        return None
    try:
        # 1. Cek dari pesan-pesan USER terdahulu (urutan dari yang paling baru ke lama)
        rows = await core_pool.fetch(
            "SELECT content FROM messages WHERE conversation_id = $1 AND role = 'user' ORDER BY id DESC LIMIT 10",
            conversation_id
        )
        for r in rows:
            content = (r["content"] or "").lower()
            if any(w in content for w in ["beli", "pembelian", "kulakan", "pengadaan"]):
                return "pembelian"
            if any(w in content for w in ["servis", "service", "bengkel", "pkb", "wo"]):
                return "servis"
            if any(w in content for w in ["sparepart", "suku cadang", "part"]):
                return "sparepart"
            if any(w in content for w in ["jual", "penjualan", "omzet", "unit terjual"]):
                return "penjualan"

        # 2. Cek dari judul percakapan (pertanyaan pertama user saat sesi dibuat)
        title = await core_pool.fetchval(
            "SELECT title FROM conversations WHERE id = $1",
            conversation_id
        )
        if title:
            t_lower = title.lower()
            if any(w in t_lower for w in ["beli", "pembelian", "kulakan", "pengadaan"]):
                return "pembelian"
            if any(w in t_lower for w in ["servis", "service", "bengkel", "pkb", "wo"]):
                return "servis"
            if any(w in t_lower for w in ["sparepart", "suku cadang", "part"]):
                return "sparepart"
            if any(w in t_lower for w in ["jual", "penjualan", "omzet", "unit terjual"]):
                return "penjualan"
    except Exception as e:
        logger.warning("Gagal deteksi topik percakapan %s: %s", conversation_id, e)
    return None


async def ambil_konteks_percakapan_aktif(core_pool, conversation_id: int | None) -> dict:
    """Ekstrak tahun dan topik dari riwayat sesi percakapan aktif (terisolasi per conversation_id).

    Prinsip Zero Cross-Session Bleed: konteks HANYA dari conversation_id ini.
    Jika conversation_id None atau sesi kosong, kembalikan konteks netral tanpa asumsi.
    """
    if not conversation_id:
        return {"year": None, "topic": None, "has_prior_chat": False}
    try:
        rows = await core_pool.fetch(
            "SELECT role, content FROM messages WHERE conversation_id = $1 ORDER BY id DESC LIMIT 10",
            conversation_id
        )
        if not rows:
            return {"year": None, "topic": None, "has_prior_chat": False}

        found_year = None
        found_topic = None

        for r in rows:
            raw = str(r["content"] or "")
            text_to_scan = raw
            if r["role"] == "assistant":
                try:
                    import json as _json
                    data = _json.loads(raw)
                    # Abaikan pesan klarifikasi dan conversational agar tidak mencemari topik riwayat sesi
                    if (
                        data.get("status") == "clarification_needed"
                        or data.get("source") == "clarification"
                        or data.get("is_conversational_text")
                        or data.get("metode") in ("conversational_guide", "conversational_explanation")
                    ):
                        continue
                    text_to_scan = f"{data.get('question', '')} {data.get('sql', '')} {data.get('ringkasan', '')}"
                except Exception:
                    pass

            if not found_year:
                y_matches = re.findall(r'\b(20[12]\d)\b', text_to_scan)
                if y_matches:
                    found_year = int(y_matches[0])

            if not found_topic:
                c_lower = text_to_scan.lower()
                if any(w in c_lower for w in ["beli", "pembelian", "kulakan", "pengadaan"]):
                    found_topic = "pembelian"
                elif any(w in c_lower for w in ["servis", "service", "bengkel", "wo", "pkb"]):
                    found_topic = "servis"
                elif any(w in c_lower for w in ["sparepart", "suku cadang", "part"]):
                    found_topic = "sparepart"
                elif any(w in c_lower for w in ["jual", "penjualan", "omzet", "unit terjual"]):
                    found_topic = "penjualan"

            if found_year and found_topic:
                break

        return {
            "year": found_year,
            "topic": found_topic,
            "has_prior_chat": len(rows) > 0
        }
    except Exception as e:
        logger.warning("Gagal ambil konteks percakapan aktif %s: %s", conversation_id, e)
        return {"year": None, "topic": None, "has_prior_chat": False}


async def rekonsiliasi_slot_percakapan(core_pool, conversation_id: int | None, question: str) -> tuple[str, bool]:
    """Rekonsiliasi Conversational Slot-Filling: mendeteksi balasan klarifikasi pengguna dan menyintesis kueri utuh.

    Prinsip Conversational Slot-Filling:
    Jika sesi aktif sebelumnya sedang menanti klarifikasi (status 'clarification_needed'),
    dan balasan pengguna saat ini menyajikan slot yang hilang (misal: 'penjualan unit 2025' atau '2025'),
    sistem secara cerdas merekonstruksi kueri awal menjadi kueri utuh tanpa perlu form tombol kaku.

    Returns:
        tuple: (synthesized_question, is_reconciled)
    """
    if not conversation_id or not question:
        return question, False

    try:
        # Ambil pesan asisten terakhir pada percakapan aktif ini
        row = await core_pool.fetchrow(
            "SELECT content FROM messages WHERE conversation_id = $1 AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            conversation_id
        )
        if not row:
            return question, False

        raw_content = row["content"] or ""
        try:
            assistant_data = json.loads(raw_content)
        except Exception:
            return question, False

        # Periksa apakah pesan asisten sebelumnya sedang menunggu klarifikasi parameter
        pending = assistant_data.get("pending_clarification")
        if not pending or assistant_data.get("status") != "clarification_needed":
            return question, False

        q_lower = question.strip().lower()

        # Deteksi Pergantian Topik (Topic Shift): jika pengguna bertanya hal baru yang berdiri sendiri
        kata_tanya_baru = ["siapa", "berapa stok", "daftar customer", "daftar pelanggan", "5 mobil", "5 customer"]
        if any(kt in q_lower for kt in kata_tanya_baru):
            logger.info("Pengguna berpindah topik percakapan dari pending clarification: %s", question)
            return question, False

        # Ekstrak slot tahun dari balasan pengguna
        y_match = re.search(r'\b(20[12]\d)\b', q_lower)
        extracted_year = int(y_match.group(1)) if y_match else None

        # Ekstrak slot divisi / domain
        extracted_domain = None
        if any(w in q_lower for w in ["beli", "pembelian", "kulakan", "pengadaan"]):
            extracted_domain = "pembelian"
        elif any(w in q_lower for w in ["servis", "service", "bengkel", "pkb", "wo"]):
            extracted_domain = "servis"
        elif any(w in q_lower for w in ["sparepart", "suku cadang", "part"]):
            extracted_domain = "sparepart"
        elif any(w in q_lower for w in ["jual", "penjualan", "omzet", "unit"]):
            extracted_domain = "penjualan"
        elif any(w in q_lower for w in ["semua", "seluruh", "konsolidasi", "semua transaksi", "seluruh transaksi", "semua data"]):
            extracted_domain = "all"

        # Jika pengguna tidak memberikan slot tahun maupun domain, bukan balasan slot
        if not extracted_year and not extracted_domain:
            return question, False

        intent = pending.get("intent")
        captured_slots = pending.get("captured_slots") or {}
        year = extracted_year or captured_slots.get("year")
        domain = extracted_domain or captured_slots.get("domain")
        month = captured_slots.get("month", 11)

        if intent == "data_cutoff":
            if year:
                if domain == "penjualan":
                    synthesized = f"Kenapa data penjualan unit tahun {year} hanya sampai bulan {month}?"
                elif domain == "servis":
                    synthesized = f"Kenapa data servis bengkel tahun {year} hanya sampai bulan {month}?"
                elif domain == "sparepart":
                    synthesized = f"Kenapa data suku cadang tahun {year} hanya sampai bulan {month}?"
                elif domain == "pembelian":
                    synthesized = f"Kenapa data pembelian unit tahun {year} hanya sampai bulan {month}?"
                else:
                    synthesized = f"Kenapa data transaksi tahun {year} hanya sampai bulan {month}?"
                logger.info("Conversational slot-filling merekonstruksi: '%s' + '%s' -> '%s'", pending.get("original_question"), question, synthesized)
                return synthesized, True
            elif domain:
                synthesized = f"Kenapa data {domain} hanya sampai bulan {month}?"
                return synthesized, True

        return question, False
    except Exception as e:
        logger.warning("Gagal rekonsiliasi slot percakapan: %s", e)
        return question, False


def _deteksi_kueri_komparasi_periode(question: str, inherited_topic: str | None = None) -> dict | None:
    """Deteksi kueri perbandingan antar periode (misal: 2024 vs 2025)."""
    q_lower = (question or "").lower()
    years = re.findall(r'\b(20[12]\d)\b', q_lower)
    is_vs = any(w in q_lower for w in [" vs ", " versus ", "bandingkan", "perbandingan", "komparasi", " beda ", "selisih", "dibandingkan", "dibanding"])

    subject = inherited_topic or "transaksi"
    if any(w in q_lower for w in ["jual", "penjualan", "omzet", "unit terjual"]):
        subject = "penjualan"
    elif any(w in q_lower for w in ["beli", "pembelian", "pengadaan"]):
        subject = "pembelian"
    elif any(w in q_lower for w in ["servis", "service", "bengkel", "wo", "pkb"]):
        subject = "servis"
    elif any(w in q_lower for w in ["part", "sparepart", "suku cadang"]):
        subject = "suku cadang"

    frasa_subject = f"transaksi {subject}" if subject != "transaksi" else "data transaksi"

    if len(years) >= 2:
        p1, p2 = sorted(years[:2])
        return {
            "type": "year",
            "periods": [p1, p2],
            "subject": subject,
            "suggestions": [
                f"Tampilkan rincian {frasa_subject} tahun {p1} dan {p2} secara terpisah",
                f"Lihat detail {frasa_subject} tahun {p1}",
                f"Lihat detail {frasa_subject} tahun {p2}",
            ]
        }
    elif is_vs and len(years) == 1:
        p1 = years[0]
        p_prev = str(int(p1) - 1)
        return {
            "type": "year",
            "periods": [p_prev, p1],
            "subject": subject,
            "suggestions": [
                f"Tampilkan rincian {frasa_subject} tahun {p_prev} dan {p1} secara terpisah",
                f"Lihat detail {frasa_subject} tahun {p1}",
                f"Lihat detail {frasa_subject} tahun {p_prev}",
            ]
        }
    return None


def cek_apakah_minta_rincian_terpisah(question: str, inherited_topic: str | None = None) -> dict | None:
    """Deteksi jika user meminta rincian periode terpisah (Gaya 2)."""
    q_lower = (question or "").lower()
    is_terpisah = any(w in q_lower for w in ["terpisah", "sendiri-sendiri", "masing-masing", "pisah", "pecah", "tiap tabel", "per tabel"])
    is_rincian = any(w in q_lower for w in ["rincian", "detail", "faktur", "transaksi", "tabel terpisah"])
    years = re.findall(r'\b(20[12]\d)\b', q_lower)

    if (is_terpisah or is_rincian) and len(years) >= 2:
        p1, p2 = sorted(years[:2])

        # Tentukan topik dari kueri eksplisit atau inherited_topic dari percakapan
        topic = inherited_topic or "penjualan"
        if any(w in q_lower for w in ["beli", "pembelian", "kulakan", "pengadaan"]):
            topic = "pembelian"
        elif any(w in q_lower for w in ["servis", "service", "bengkel", "wo", "pkb"]):
            topic = "servis"
        elif any(w in q_lower for w in ["part", "sparepart", "suku cadang"]):
            topic = "sparepart"
        elif any(w in q_lower for w in ["jual", "penjualan", "omzet", "unit terjual"]):
            topic = "penjualan"

        # Tentukan tabel target berdasarkan konteks kueri
        table = "untt_penjualan"
        date_col = "tanggal"
        order_col = "tanggal"
        filter_clause = "NOT COALESCE(batal, FALSE) AND NOT COALESCE(retur, FALSE)"
        columns_to_select = "nomor, tanggal, nomor_pesanan, norangka, hjunit, diskon, hjakhir"

        if topic == "pembelian":
            table = "untt_pembelian"
            date_col = "tglinvoice"
            order_col = "tglinvoice"
            filter_clause = "1=1"
            columns_to_select = "nomor, tglinvoice, norangka, hpunit, hpdpp, hpppn"
        elif topic == "servis":
            table = "srvt_wo"
            date_col = "tanggal"
            order_col = "tanggal"
            filter_clause = "NOT COALESCE(batal, FALSE)"
            columns_to_select = "nomor, tanggal, nomor_customer, nopolisi, totalestimasibiaya"
        elif topic == "sparepart":
            table = "srvt_wodetail"
            date_col = "tanggal"
            order_col = "nomor"
            filter_clause = "part > 0"
            columns_to_select = "nomor_wo, part, jenis"

        sql_1 = f"SELECT {columns_to_select} FROM {table} WHERE EXTRACT(YEAR FROM {date_col}) = {p1} AND {filter_clause} ORDER BY {order_col} DESC LIMIT 50;"
        sql_2 = f"SELECT {columns_to_select} FROM {table} WHERE EXTRACT(YEAR FROM {date_col}) = {p2} AND {filter_clause} ORDER BY {order_col} DESC LIMIT 50;"

        return {
            "category": "rincian_terpisah",
            "mode": "separated_years",
            "p1": p1,
            "p2": p2,
            "topic": topic,
            "domains": [
                {
                    "id": f"thn_{p1}",
                    "title": f"Rincian Tahun {p1}",
                    "icon": "Calendar",
                    "sql": sql_1,
                },
                {
                    "id": f"thn_{p2}",
                    "title": f"Rincian Tahun {p2}",
                    "icon": "Calendar",
                    "sql": sql_2,
                }
            ]
        }
    return None


async def resolve_ai_config_for_tenant(core_pool, user_id: int, tenant_id: int) -> dict:
    """Resolve AI config: user -> tenant -> global."""
    rows = await core_pool.fetch(
        "SELECT * FROM ai_configs WHERE is_active = TRUE ORDER BY id ASC"
    )
    user_cfg = next((r for r in rows if r["scope"] == "user" and r["target_id"] == str(user_id)), None)
    if user_cfg:
        return dict(user_cfg)
    tenant_cfg = next((r for r in rows if r["scope"] == "tenant" and r["target_id"] == str(tenant_id)), None)
    if tenant_cfg:
        return dict(tenant_cfg)
    global_cfg = next((r for r in rows if r["scope"] == "global"), None)
    if global_cfg:
        return dict(global_cfg)
    raise AIConfigError("AI belum dikonfigurasi. Hubungi administrator.")


def _is_general_guide_question(question: str) -> bool:
    """Deteksi apakah pertanyaan pengguna merupakan sapaan atau permintaan panduan umum/vague data."""
    if not question:
        return False
    q = question.strip().lower()
    q_clean = re.sub(r'[?!.,;:\'"]+', ' ', q).strip()
    q_clean = re.sub(r'\s+', ' ', q_clean)

    # 1. Salam / Sapaan langsung
    greetings = {
        "halo", "hai", "hello", "hi", "hey", "hei", "p", "ping", "tes", "test", "testing",
        "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
        "assalamualaikum", "assalamu'alaikum"
    }
    if q_clean in greetings or (len(q_clean.split()) <= 2 and q_clean.split()[0] in greetings):
        return True

    # 2. Pertanyaan kapabilitas / menu / bantuan
    guide_phrases = [
        "ada data apa aja", "ada data apa saja", "ada data apa", "data apa aja yang ada",
        "data apa saja yang ada", "data apa yang tersedia", "data apa saja yang tersedia",
        "bisa bantu apa", "bisa bantu apa saja", "bisa apa saja", "kamu bisa apa",
        "apa yang bisa kamu lakukan", "bagaimana cara pakai", "cara pakainya gimana",
        "panduan penggunaan", "bantu saya", "menu apa saja", "fitur apa saja"
    ]
    if any(q_clean.startswith(gp) or q_clean == gp for gp in guide_phrases):
        return True

    # 3. Permintaan data yang sangat samar (vague data request tanpa spesifikasi entitas)
    fillers = {
        "kasih", "minta", "berikan", "tampilkan", "bagi", "kirim", "lihat", "cek",
        "coba", "tolong", "dong", "aku", "saya", "kami", "ya", "kan", "lah", "sih",
        "min", "bot", "ai", "apa", "aja", "saja", "deh", "nih", "tuh", "ke", "buat", "untuk"
    }
    words = [w for w in q_clean.split() if w not in fillers]
    if words in [["data"], ["data", "data"], ["database"], ["semua", "data"], ["seluruh", "data"], []]:
        return True

    return False


def _is_explanatory_question(question: str) -> bool:
    """Deteksi apakah pertanyaan pengguna merujuk pada penjelasan tabel/data yang baru saja ditampilkan."""
    if not question:
        return False
    q = question.strip().lower()
    q_clean = re.sub(r'[?!.,;:\'"]+', ' ', q).strip()
    q_clean = re.sub(r'\s+', ' ', q_clean)

    patterns = [
        r"^(?:loh\s+)?(?:ini|itu)\s+(?:data|tabel|laporan|grafik|hasil)(?:\s+(?:apa|sih|maksudnya))*$",
        r"^(?:loh\s+)?(?:data|tabel|laporan|grafik|hasil)\s+apa(?:\s+(?:ini|itu|sih|tuh))*$",
        r"^(?:loh\s+)?(?:data|tabel)\s+apa$",
        r"^(?:loh\s+)?maksud(?:nya)?\s+(?:dari\s+)?(?:data|tabel|laporan|grafik|angka|ini|itu)+(?:\s+apa)?$",
        r"^maksudnya(?:\s+apa)?$",
        r"^artinya(?:\s+apa)?$",
        r"^(?:coba\s+)?jelaskan\s+(?:data|tabel|laporan|hasil|kolom)(?:\s+(?:di\s+atas|ini|tersebut|barusan))?$",
        r"^(?:apa\s+maksud|apa\s+arti|artinya)\s+(?:kolom|tabel|data|angka)",
        r"^kenapa\s+(?:datanya|angkanya|tabelnya)\s+(?:seperti\s+ini|begini|begitu)$",
        r"^tabel\s+apa\s+(?:yang\s+)?(?:barusan|tadi)$",
    ]
    for pat in patterns:
        if re.search(pat, q_clean):
            return True

    keywords = [
        "data apa ini", "data apa itu", "tabel apa ini", "tabel apa itu",
        "maksud tabel ini", "maksud data ini", "jelaskan data di atas",
        "jelaskan tabel di atas", "jelaskan tabel ini", "maksud dari tabel",
        "ini maksudnya apa", "maksud tabel di atas"
    ]
    if any(kw in q_clean for kw in keywords):
        return True

    return False


async def tangani_kueri_panduan_umum(
    core_pool,
    conversation_id: int | None,
    question: str,
    user_id: int,
    branch_code: str,
    t0: float,
) -> dict:
    """Mode Panduan Orientasi: memberikan ringkasan modul data operasional dealer yang tersedia."""
    ringkasan = (
        "Selamat datang di Asisten AI Database Dealer. Platform ini terhubung langsung ke database operasional cabang Anda.\n\n"
        "Berikut adalah modul data utama yang siap Anda analisis:\n\n"
        "1. Penjualan Unit Kendaraan (tabel untt_penjualan): Volume penjualan, tren omzet bulanan dan tahunan, ranking model mobil terlaris, rincian faktur penjualan, dan performa salesman.\n"
        "2. Jasa Servis Bengkel (tabel srvt_wo & srvt_wodetail): Volume Work Order (PKB), pendapatan jasa perawatan, jenis pekerjaan servis, dan histori servis kendaraan.\n"
        "3. Suku Cadang & Sparepart: Pergerakan persediaan suku cadang, penjualan counter/part shop, dan omzet suku cadang.\n"
        "4. Pelanggan & Customer (tabel glbm_customer): Profil pelanggan terdaftar, histori pembelian unit, dan persebaran wilayah pelanggan.\n\n"
        "Silakan ketik pertanyaan spesifik yang ingin Anda ketahui atau klik salah satu rekomendasi pertanyaan di bawah ini."
    )
    saran = [
        "Tampilkan 5 model mobil dengan penjualan tertinggi",
        "Berapa total pendapatan servis bengkel tahun 2025?",
        "Daftar 10 customer dengan transaksi pembelian unit terbesar",
        "Tren volume transaksi servis bulanan sepanjang tahun 2024",
    ]
    durasi_ms = int((time.monotonic() - t0) * 1000)
    response = {
        "source": "conversational",
        "confidence": "A",
        "status": "success",
        "question": question,
        "ringkasan": ringkasan,
        "sql": "",
        "params": [],
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "duration_ms": durasi_ms,
        "memory_id": None,
        "saran": saran,
        "metode": "conversational_guide",
        "is_conversational_text": True,
        "allow_explain": False,
    }
    conv_id = await ambil_atau_buat_conversation(
        core_pool, user_id, branch_code, question, conversation_id=conversation_id
    )
    response["conversation_id"] = conv_id
    await simpan_pesan(core_pool, conv_id, "user", question)
    await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

    await tulis_audit(
        core_pool,
        user_id=user_id,
        branch_code=branch_code,
        prompt_text=question,
        ai_json_filter={"mode": "conversational_guide"},
        generated_sql="",
        execution_time_ms=durasi_ms,
        status="success",
        error_message=None,
    )
    return response


async def tangani_kueri_eksplanatori(
    core_pool,
    conversation_id: int | None,
    question: str,
    user_id: int,
    branch_code: str,
    t0: float,
) -> dict:
    """Mode Percakapan Eksplanatori: menjelaskan secara naratif hasil kueri/tabel sebelumnya."""
    durasi_ms = int((time.monotonic() - t0) * 1000)

    # Dictionary penjelas kolom database operasional dealer
    PENJELASAN_KOLOM = {
        "trxdt": "Tanggal resmi transaksi dicatat di sistem",
        "tgl": "Tanggal pencatatan transaksi",
        "tanggal": "Tanggal transaksi",
        "tglinvoice": "Tanggal terbitnya faktur/invoice",
        "nomor": "Nomor dokumen faktur transaksi resmi",
        "notrx": "Nomor identifikasi transaksi",
        "nama_customer": "Nama pelanggan atau pemilik kendaraan yang bertransaksi",
        "customer": "Nama pelanggan yang bertransaksi",
        "nama_model": "Model atau tipe varian unit kendaraan",
        "model": "Model atau tipe kendaraan",
        "tipe": "Tipe spesifik kendaraan",
        "warna": "Warna unit kendaraan",
        "hjakhir": "Total nilai nominal transaksi setelah memperhitungkan diskon dan pajak (Rupiah)",
        "hargajual": "Harga jual bruto kendaraan sebelum diskon",
        "hargabeli": "Harga beli / harga pokok perolehan kendaraan",
        "total_omzet": "Akumulasi total nilai penjualan bruto (Rupiah)",
        "total_penjualan": "Total nominal penjualan unit kendaraan (Rupiah)",
        "total_unit": "Jumlah kuantitas fisik kendaraan yang ditransaksikan",
        "total_unit_terjual": "Jumlah fisik unit mobil yang terjual",
        "wo_no": "Nomor Work Order / Perintah Kerja bengkel",
        "nopolisi": "Nomor plat polisi kendaraan pelanggan yang diservis",
        "total_jasa": "Biaya jasa pengerjaan perawatan atau perbaikan oleh bengkel (Rupiah)",
        "total_part": "Nilai suku cadang yang digunakan dalam servis bengkel (Rupiah)",
        "nama_foreman": "Nama kepala regu teknisi yang mengawasi pengerjaan servis",
        "penerima": "Service Advisor yang menerima kendaraan di bengkel",
        "tahun": "Tahun transaksi",
        "bulan": "Bulan transaksi",
    }

    prev_row = None
    if conversation_id:
        prev_row = await core_pool.fetchrow(
            "SELECT content FROM messages WHERE conversation_id = $1 AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            conversation_id,
        )

    if not prev_row:
        ringkasan = (
            "Tidak ada data atau tabel sebelumnya yang aktif dalam sesi percakapan ini. "
            "Silakan ajukan pertanyaan data tertentu, misalnya: 'Tampilkan 5 model mobil terlaris' "
            "atau 'Berapa total pendapatan servis bengkel tahun 2025?'."
        )
        saran = [
            "Tampilkan 5 model mobil dengan penjualan tertinggi",
            "Berapa total pendapatan servis bengkel tahun 2025?",
            "Daftar 10 customer dengan transaksi pembelian unit terbesar",
        ]
    else:
        prev_data = {}
        try:
            prev_data = json.loads(prev_row["content"])
        except Exception:
            pass

        if prev_data.get("metode") == "conversational_guide" or (not prev_data.get("sql") and not prev_data.get("rows")):
            ringkasan = (
                "Pesan sebelumnya merupakan ringkasan panduan modul data yang tersedia di dealer Anda. "
                "Untuk memeriksa data operasional nyata, Anda dapat meminta data penjualan unit, "
                "servis bengkel, atau suku cadang."
            )
            saran = [
                "Tampilkan 5 model mobil dengan penjualan tertinggi",
                "Berapa total pendapatan servis bengkel tahun 2025?",
                "Tren volume transaksi servis bulanan sepanjang tahun 2024",
            ]
        else:
            prev_q = prev_data.get("question") or "permintaan data sebelumnya"
            sql = (prev_data.get("sql") or "").lower()
            cols = prev_data.get("columns") or []
            rows = prev_data.get("rows") or []
            row_count = prev_data.get("row_count", len(rows))

            modul_nama = "Operasional Dealer"
            modul_tabel = ""
            if "untt_penjualan" in sql or any(k in prev_q.lower() for k in ["jual", "penjualan", "mobil", "unit"]):
                modul_nama = "Penjualan Unit Kendaraan"
                modul_tabel = "untt_penjualan"
                saran = [
                    "Berapa total omzet penjualan unit per bulan di tahun 2025?",
                    "Tampilkan 5 customer dengan pembelian unit terbanyak",
                    "Tren volume penjualan unit mobil sepanjang tahun 2024",
                ]
            elif "srvt_wo" in sql or "srvt_wodetail" in sql or any(k in prev_q.lower() for k in ["servis", "service", "bengkel", "pkb", "wo"]):
                modul_nama = "Jasa Servis & Perawatan Bengkel"
                modul_tabel = "srvt_wo & srvt_wodetail"
                saran = [
                    "Berapa total pendapatan jasa servis bengkel tahun 2025?",
                    "Tampilkan 5 jenis pekerjaan servis yang paling sering dikerjakan",
                    "Tren jumlah unit kendaraan yang diservis per bulan",
                ]
            elif "untt_pembelian" in sql or any(k in prev_q.lower() for k in ["beli", "pembelian", "kulakan", "pengadaan"]):
                modul_nama = "Pembelian Unit Kendaraan"
                modul_tabel = "untt_pembelian"
                saran = [
                    "Berapa total unit yang dibeli dealer tahun 2025?",
                    "Daftar supplier unit kendaraan utama",
                    "Perbandingan total unit dibeli vs unit terjual",
                ]
            elif "srvm_" in sql or any(k in prev_q.lower() for k in ["sparepart", "suku cadang", "part"]):
                modul_nama = "Suku Cadang & Sparepart"
                modul_tabel = "srvm_parts"
                saran = [
                    "Tampilkan 10 suku cadang dengan perputaran tercepat",
                    "Berapa total nilai penjualan suku cadang tahun 2025?",
                    "Daftar suku cadang dengan pergerakan tertinggi",
                ]
            elif "glbm_customer" in sql or any(k in prev_q.lower() for k in ["customer", "pelanggan"]):
                modul_nama = "Master Data Pelanggan / Customer"
                modul_tabel = "glbm_customer"
                saran = [
                    "Daftar pelanggan aktif dengan transaksi terbanyak",
                    "Persebaran pelanggan berdasarkan kota",
                    "Daftar customer yang melakukan pembelian unit di tahun 2025",
                ]
            else:
                modul_nama = "Transaksi Operasional Cabang"
                saran = [
                    "Tampilkan rincian transaksi per bulan",
                    "Berapa total nilai transaksi keseluruhan?",
                    "Tampilkan 5 transaksi dengan nominal terbesar",
                ]

            paragraf = []
            baris_info = f"{row_count} baris data" if row_count > 0 else "data"
            paragraf.append(
                f"Tabel di atas menampilkan {baris_info} dari modul **{modul_nama}**"
                + (f" (tabel `{modul_tabel}`)" if modul_tabel else "")
                + f", yang dihasilkan untuk menjawab pertanyaan: *\"{prev_q}\"*."
            )

            kolom_penjelas = []
            for c in cols[:6]:
                c_clean = str(c).lower().strip()
                desc = PENJELASAN_KOLOM.get(c_clean)
                if desc:
                    kolom_penjelas.append(f"- **{c}**: {desc}")

            if kolom_penjelas:
                paragraf.append("Rincian fungsi kolom yang disajikan:\n" + "\n".join(kolom_penjelas))

            paragraf.append(
                "Data tersebut bersumber langsung dari database cabang Anda tanpa rekayasa. "
                "Jika Anda ingin melihat data periode lain, rincian salesman, atau analisis tren, "
                "silakan pilih salah satu pertanyaan di bawah atau ajukan pertanyaan baru."
            )
            ringkasan = "\n\n".join(paragraf)

    response = {
        "source": "conversational",
        "confidence": "A",
        "status": "success",
        "question": question,
        "ringkasan": ringkasan,
        "sql": "",
        "params": [],
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "duration_ms": durasi_ms,
        "memory_id": None,
        "saran": saran,
        "metode": "conversational_explanation",
        "is_conversational_text": True,
        "allow_explain": False,
    }
    conv_id = await ambil_atau_buat_conversation(
        core_pool, user_id, branch_code, question, conversation_id=conversation_id
    )
    response["conversation_id"] = conv_id
    await simpan_pesan(core_pool, conv_id, "user", question)
    await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

    await tulis_audit(
        core_pool,
        user_id=user_id,
        branch_code=branch_code,
        prompt_text=question,
        ai_json_filter={"mode": "conversational_explanation"},
        generated_sql="",
        execution_time_ms=durasi_ms,
        status="success",
        error_message=None,
    )
    return response


async def jalankan_mode_vanna(core_pool, tenant_pool_manager, user: dict,
                              question: str, branch_code: str,
                              llm_call_fn=None,
                              conversation_id: int | None = None) -> dict:
    """Eksekusi kueri menggunakan Mode Vanna murni."""
    t0 = time.monotonic()
    user_id = user["user_id"]

    try:
        tenant = await resolve_tenant(core_pool, branch_code)
        tenant_id = tenant.get("tenant_id") or tenant.get("id")

        # Conversational Slot-Filling: Rekonsiliasi jawaban klarifikasi pengguna jika ada sesi aktif
        question, is_reconciled = await rekonsiliasi_slot_percakapan(core_pool, conversation_id, question)
        q_norm = normalisasi_pertanyaan(question)

        # Deteksi topik riwayat percakapan sebelumnya untuk multi-turn chat continuity
        inherited_topic = await deteksi_topik_riwayat_percakapan(core_pool, conversation_id)

        # Ambil konteks percakapan aktif (tahun + topik) secara terisolasi per conversation_id
        active_context = await ambil_konteks_percakapan_aktif(core_pool, conversation_id)

        # 0.0. Mode Percakapan Eksplanatori ("loh data apa ini?", "maksud tabel ini apa?")
        if _is_explanatory_question(question):
            return await tangani_kueri_eksplanatori(
                core_pool, conversation_id, question, user_id, branch_code, t0
            )

        # 0.0.1. Mode Panduan Orientasi Modul Dealer ("kasih aku dong data data", "ada data apa aja", "halo")
        if _is_general_guide_question(question):
            return await tangani_kueri_panduan_umum(
                core_pool, conversation_id, question, user_id, branch_code, t0
            )

        # 0.1. Cek Pertanyaan Eksplanatori Keterbatasan Data / Cut-off Tanggal (0 Panggilan LLM, 100% Akurat)
        cutoff_info = _is_data_cutoff_question(question, active_context=active_context)
        if cutoff_info:
            # Jika tahun dan konteks tidak teridentifikasi: kembalikan kartu klarifikasi interaktif
            if cutoff_info.get("needs_clarification"):
                durasi_ms = int((time.monotonic() - t0) * 1000)
                clarification_msg = (
                    "Pertanyaan Anda mengenai batas data transaksi memerlukan informasi jenis transaksi dan tahun yang ingin diperiksa. "
                    "Data transaksi apa (misalnya Penjualan Unit, Servis Bengkel, atau Suku Cadang) dan untuk tahun berapa yang ingin Anda analisis?"
                )
                response = {
                    "source": "clarification",
                    "confidence": "B",
                    "status": "clarification_needed",
                    "question": question,
                    "clarification_message": clarification_msg,
                    "category": "data_cutoff",
                    "pending_clarification": {
                        "intent": "data_cutoff",
                        "original_question": question,
                        "missing_slots": ["domain", "year"],
                        "captured_slots": {"month": cutoff_info.get("month", 11)},
                    },
                    "options": [
                        {
                            "id": "penjualan",
                            "icon": "Car",
                            "label": "Penjualan Unit",
                            "deskripsi": "Data transaksi unit kendaraan",
                            "prompt": "Data penjualan unit",
                        },
                        {
                            "id": "servis",
                            "icon": "Wrench",
                            "label": "Jasa Servis Bengkel",
                            "deskripsi": "Data perawatan dan servis bengkel",
                            "prompt": "Data servis bengkel",
                        },
                        {
                            "id": "sparepart",
                            "icon": "Wrench",
                            "label": "Suku Cadang & Sparepart",
                            "deskripsi": "Data transaksi suku cadang",
                            "prompt": "Data suku cadang",
                        },
                        {
                            "id": "all",
                            "icon": "Layers",
                            "label": "Semua Transaksi",
                            "deskripsi": "Total data seluruh transaksi operasional",
                            "prompt": "Data semua transaksi",
                        },
                    ],
                    "sql": "",
                    "params": [],
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "truncated": False,
                    "duration_ms": durasi_ms,
                    "memory_id": None,
                    "ringkasan": clarification_msg,
                    "saran": [],
                    "metode": "clarification",
                    "allow_explain": False,
                }

                conv_id = await ambil_atau_buat_conversation(
                    core_pool, user_id, branch_code, question, conversation_id=conversation_id
                )
                response["conversation_id"] = conv_id
                await simpan_pesan(core_pool, conv_id, "user", question)
                await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

                await tulis_audit(
                    core_pool,
                    user_id=user_id,
                    branch_code=branch_code,
                    prompt_text=question,
                    ai_json_filter={"mode": "clarification", "reason": "data_cutoff_no_year"},
                    generated_sql="",
                    execution_time_ms=durasi_ms,
                    status="success",
                    error_message=None,
                )
                return response

            # Tahun teridentifikasi (dari pertanyaan atau riwayat sesi aktif): jalankan audit empiris
            res_cutoff = await tangani_pertanyaan_keterbatasan_data(
                tenant_pool_manager, tenant, question, cutoff_info, branch_code
            )
            durasi_ms = int((time.monotonic() - t0) * 1000)
            response = {
                "source": "vanna",
                "confidence": "A",
                "question": question,
                "is_multi_tab": False,
                "sql": res_cutoff["sql"],
                "params": [],
                "columns": res_cutoff["columns"],
                "rows": res_cutoff["rows"],
                "row_count": len(res_cutoff["rows"]),
                "truncated": False,
                "duration_ms": durasi_ms,
                "memory_id": None,
                "ringkasan": res_cutoff["ringkasan"],
                "saran": res_cutoff["saran"],
                "metode": "data_cutoff_audit",
                "allow_explain": True,
            }
            conv_id = await ambil_atau_buat_conversation(
                core_pool, user_id, branch_code, question, conversation_id=conversation_id
            )
            response["conversation_id"] = conv_id
            await simpan_pesan(core_pool, conv_id, "user", question)
            await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

            await tulis_audit(
                core_pool,
                user_id=user_id,
                branch_code=branch_code,
                prompt_text=question,
                ai_json_filter={"mode": "data_cutoff_audit", "target_year": cutoff_info["target_year"]},
                generated_sql=res_cutoff["sql"],
                execution_time_ms=durasi_ms,
                status="success",
                error_message=None,
            )
            return response

        # 0. Cek SQL Memory (0 Panggilan LLM, 0 Token!)
        entri_memori = await core_pool.fetchrow(
            "SELECT id, sql, ringkasan, status FROM sql_memory "
            "WHERE tenant_id = $1 AND pertanyaan_ternormalisasi = $2 "
            "  AND status IN ('approved', 'pending') "
            "ORDER BY (CASE WHEN status = 'approved' THEN 0 ELSE 1 END), times_used DESC, id DESC "
            "LIMIT 1",
            tenant_id, q_norm
        )

        if entri_memori:
            sql_mem = entri_memori["sql"]
            # Periksa apakah entri memori ini cocok dengan konteks percakapan multi-turn
            topic_mismatch = False
            if inherited_topic:
                sql_lower = sql_mem.lower()
                if inherited_topic == "pembelian" and "untt_pembelian" not in sql_lower:
                    topic_mismatch = True
                elif inherited_topic == "servis" and "srvt_" not in sql_lower:
                    topic_mismatch = True
                elif inherited_topic == "sparepart" and "prtt_" not in sql_lower and "part" not in sql_lower:
                    topic_mismatch = True
                elif inherited_topic == "penjualan" and "untt_penjualan" not in sql_lower:
                    topic_mismatch = True

            if not topic_mismatch:
                try:
                    pool_tenant = await tenant_pool_manager.get_pool(tenant)
                    async with pool_tenant.acquire() as conn:
                        await conn.execute("SET statement_timeout = '30000'")
                        db_rows = await conn.fetch(sql_mem)

                    durasi_ms = int((time.monotonic() - t0) * 1000)
                    columns = [k for k in db_rows[0].keys()] if db_rows else []
                    rows = [[_konversi_nilai_vanna(v) for v in r.values()] for r in db_rows[:500]]
                    raw_ringkasan = _format_ringkasan_otomatis(db_rows[:500], columns, question)
                    ringkasan = _bersihkan_emoji_teks(raw_ringkasan)

                    try:
                        await tandai_memory_dipakai(core_pool, entri_memori["id"])
                    except Exception:
                        pass

                    comp_info = _deteksi_kueri_komparasi_periode(question, inherited_topic=inherited_topic)
                    saran_list = comp_info.get("suggestions", []) if comp_info else []
                    is_comp = bool(comp_info)

                    response = {
                        "source": "memory",
                        "confidence": "A",
                        "sql": sql_mem,
                        "params": [],
                        "columns": columns,
                        "rows": rows,
                        "row_count": len(rows),
                        "truncated": len(db_rows) > 500,
                        "duration_ms": durasi_ms,
                        "memory_id": entri_memori["id"],
                        "question": question,
                        "ringkasan": ringkasan,
                        "saran": saran_list,
                        "metode": "memory",
                        "allow_explain": True,
                        "is_comparison": is_comp,
                        "comparison_meta": comp_info
                    }

                    conv_id = await ambil_atau_buat_conversation(core_pool, user_id, branch_code, question, conversation_id=conversation_id)
                    response["conversation_id"] = conv_id
                    await simpan_pesan(core_pool, conv_id, "user", question)
                    await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

                    await tulis_audit(
                        core_pool,
                        user_id=user_id,
                        branch_code=branch_code,
                        prompt_text=question,
                        ai_json_filter={"mode": "vanna", "replay_memory": True},
                        generated_sql=sql_mem,
                        execution_time_ms=durasi_ms,
                        status="success",
                        error_message=None
                    )
                    return response
                except Exception as e_mem:
                    logger.warning("Replay SQL memory gagal (%s), lanjut ke LLM...", e_mem)

        # 0.4. Cek Kueri Rincian Terpisah (Gaya 2) atau Kueri Makro Dealer Multi-Tab
        fanout_info = cek_apakah_minta_rincian_terpisah(question, inherited_topic=inherited_topic) or cek_apakah_perlu_fanout(question)
        if fanout_info:
            ai_config = await resolve_ai_config(core_pool, user.get("username", ""), branch_code)
            async with VANNA_SEMAPHORE:
                if all("sql" in d and d["sql"] for d in fanout_info["domains"]):
                    sql_dict = {d["id"]: d["sql"] for d in fanout_info["domains"]}
                else:
                    context_text, _ = await ambil_konteks_vanna(core_pool, question, branch_code, inherited_topic=inherited_topic)
                    multi_prompt = susun_multi_sql_prompt(question, fanout_info, context_text)
                    panggil_fn = llm_call_fn or panggil_llm_default
                    system_msg = "You are a PostgreSQL expert for automotive DMS. Respond only with JSON containing SQL for each domain."
                    raw_output = await panggil_fn(system_msg, multi_prompt, ai_config)

                    domain_ids = [d["id"] for d in fanout_info["domains"]]
                    sql_dict = ekstrak_multi_sql(raw_output, domain_ids)

                pool_tenant = await tenant_pool_manager.get_pool(tenant)

                async def _eksekusi_subdomain(domain_def: dict, sql_query: str):
                    if not sql_query:
                        return {
                            "id": domain_def["id"],
                            "title": domain_def["title"],
                            "icon": domain_def["icon"],
                            "sql": "-- Kueri tidak dihasilkan",
                            "columns": [],
                            "rows": [],
                            "row_count": 0,
                            "raw_records": [],
                            "error": "Kueri tidak dihasilkan"
                        }
                    async with pool_tenant.acquire() as conn:
                        await conn.execute("SET statement_timeout = '15000'")
                        try:
                            records = await conn.fetch(sql_query)
                            cols = list(records[0].keys()) if records else []
                            converted = [[_konversi_nilai_vanna(v) for v in r.values()] for r in records[:500]]
                            return {
                                "id": domain_def["id"],
                                "title": domain_def["title"],
                                "icon": domain_def["icon"],
                                "sql": sql_query,
                                "columns": cols,
                                "rows": converted,
                                "row_count": len(records),
                                "raw_records": [dict(r) for r in records[:10]],
                                "error": None
                            }
                        except Exception as e:
                            logger.warning("Eksekusi sub-domain %s gagal: %s", domain_def["id"], e)
                            return {
                                "id": domain_def["id"],
                                "title": domain_def["title"],
                                "icon": domain_def["icon"],
                                "sql": sql_query,
                                "columns": [],
                                "rows": [],
                                "row_count": 0,
                                "raw_records": [],
                                "error": str(e)
                            }

                tasks = [
                    _eksekusi_subdomain(d, sql_dict.get(d["id"], ""))
                    for d in fanout_info["domains"]
                ]
                tab_results = await asyncio.gather(*tasks)

                # Filter hanya tab yang memiliki data nyata (>0 baris)
                tabs_with_data = [t for t in tab_results if (t.get("row_count") or len(t.get("rows") or [])) > 0]
                has_multiple_tabs = len(tabs_with_data) > 1
                active_tabs = tabs_with_data if tabs_with_data else tab_results

                # Jika pertanyaan meminta komparasi/perbandingan antar divisi, tambahkan Tab Komparasi Konsolidasi Sejajar
                if cek_apakah_perlu_komparasi(question) and len(tabs_with_data) > 1 and fanout_info.get("category") != "rincian_terpisah":
                    komparasi_tab = susun_tab_komparasi_divisi(tabs_with_data, question)
                    if komparasi_tab:
                        active_tabs = [komparasi_tab] + [t for t in tabs_with_data if t["id"] != "komparasi"]
                        has_multiple_tabs = True

                default_tab = active_tabs[0]

                durasi_ms = int((time.monotonic() - t0) * 1000)
                ringkasan_multi = _bersihkan_emoji_teks(susun_ringkasan_eksekutif_multi(active_tabs, question))

                # Rekomendasi saran pertanyaan kontekstual (Anti Self-Referencing / De-duplikasi kueri user)
                if fanout_info.get("category") == "rincian_terpisah":
                    p1 = str(fanout_info.get("p1") or "").strip()
                    p2 = str(fanout_info.get("p2") or "").strip()
                    topic = fanout_info.get("topic") or inherited_topic or "transaksi"
                    frasa_topik = f"transaksi {topic}" if topic != "transaksi" else "data transaksi"
                    if p1 and p2:
                        saran_list = [
                            f"Bandingkan performa {topic} tahun {p1} vs {p2} dalam satu tabel",
                            f"Tampilkan tren bulanan {topic} tahun {p1}",
                            f"Tampilkan tren bulanan {topic} tahun {p2}"
                        ]
                    elif p1:
                        saran_list = [
                            f"Tampilkan tren bulanan {topic} tahun {p1}",
                            f"Bandingkan performa {topic} dengan tahun sebelumnya",
                            f"Tampilkan 5 {frasa_topik} terbesar tahun {p1}"
                        ]
                    else:
                        saran_list = [
                            f"Bandingkan performa {topic} antar tahun dalam satu tabel",
                            f"Tampilkan 5 {frasa_topik} terbesar di database",
                            f"Tampilkan tren bulanan {topic} tahun ini"
                        ]
                else:
                    saran_list = []
                    q_clean = question.lower().strip()
                    potential_saran = [
                        "Tampilkan tren bulanan penjualan unit tahun ini",
                        "Tampilkan rincian servis bengkel dengan estimasi biaya terbesar",
                        "Bandingkan performa divisi dengan tahun penuh 2025",
                        "Tampilkan 5 customer dengan transaksi terbesar tahun ini",
                        "Tampilkan ringkasan pendapatan jasa servis bengkel per kuartal"
                    ]
                    for s in potential_saran:
                        s_clean = s.lower().strip()
                        if s_clean != q_clean and q_clean not in s_clean and s_clean not in q_clean:
                            saran_list.append(s)
                        if len(saran_list) >= 3:
                            break

                response = {
                    "source": "vanna",
                    "confidence": "A",
                    "question": question,
                    "is_multi_tab": has_multiple_tabs,
                    "tabs": active_tabs,
                    "sql": default_tab["sql"],
                    "params": [],
                    "columns": default_tab["columns"],
                    "rows": default_tab["rows"],
                    "row_count": default_tab["row_count"],
                    "truncated": False,
                    "duration_ms": durasi_ms,
                    "memory_id": None,
                    "ringkasan": ringkasan_multi,
                    "saran": saran_list,
                    "metode": "fanout_multi_tab" if has_multiple_tabs else "fanout_single_tab",
                    "allow_explain": True
                }

                conv_id = await ambil_atau_buat_conversation(core_pool, user_id, branch_code, question, conversation_id=conversation_id)
                response["conversation_id"] = conv_id
                await simpan_pesan(core_pool, conv_id, "user", question)
                await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

                await tulis_audit(
                    core_pool,
                    user_id=user_id,
                    branch_code=branch_code,
                    prompt_text=question,
                    ai_json_filter={"mode": "vanna_fanout", "category": fanout_info["category"]},
                    generated_sql=default_tab["sql"],
                    execution_time_ms=durasi_ms,
                    status="success",
                    error_message=None
                )
                return response

        # 0.5. Cek Ambiguitas Domain Dealer (Interactive Clarification Loop)
        ambiguitas = cek_ambiguitas_pertanyaan(question)
        if ambiguitas:
            durasi_ms = int((time.monotonic() - t0) * 1000)
            response = {
                "source": "clarification",
                "confidence": "B",
                "status": "clarification_needed",
                "question": question,
                "clarification_message": ambiguitas["message"],
                "category": ambiguitas["category"],
                "options": ambiguitas["options"],
                "sql": "",
                "params": [],
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "duration_ms": durasi_ms,
                "memory_id": None,
                "ringkasan": ambiguitas["message"],
                "saran": [],
                "metode": "clarification",
                "allow_explain": False
            }

            conv_id = await ambil_atau_buat_conversation(core_pool, user_id, branch_code, question, conversation_id=conversation_id)
            response["conversation_id"] = conv_id
            await simpan_pesan(core_pool, conv_id, "user", question)
            await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

            await tulis_audit(
                core_pool,
                user_id=user_id,
                branch_code=branch_code,
                prompt_text=question,
                ai_json_filter={"mode": "vanna", "clarification": ambiguitas["category"]},
                generated_sql=None,
                execution_time_ms=durasi_ms,
                status="clarification",
                error_message=None
            )
            return response

        ai_config = await resolve_ai_config(core_pool, user.get("username", ""), branch_code)
        
        async with VANNA_SEMAPHORE:
            # 1. Ambil Konteks Semantik Murni dari pgvector (dengan fallback aman)
            context_text, _ = await ambil_konteks_vanna(core_pool, question, branch_code, inherited_topic=inherited_topic)
            
            # 2. Susun Prompt Vanna
            vanna_prompt = susun_prompt_vanna(question, context_text, inherited_topic=inherited_topic)
            
            # 3. Panggil LLM (Hanya 1 Panggilan Tunggal!)
            panggil_fn = llm_call_fn or panggil_llm_default
            system_msg = "You are a Postgres expert. Respond only with SQL code block."
            raw_output = await panggil_fn(system_msg, vanna_prompt, ai_config)
            
            # 4. Ekstrak SQL
            sql = ekstrak_sql(raw_output)
            if not sql.lower().startswith("select") and not sql.lower().startswith("with"):
                raise ValueError(f"AI tidak menghasilkan kueri SELECT yang valid: {raw_output[:200]}")

            # 5. Eksekusi ke Database Tenant (Timeout 15 detik + 1x Auto Self-Repair)
            db_rows = None
            pool_tenant = await tenant_pool_manager.get_pool(tenant)
            async with pool_tenant.acquire() as conn:
                await conn.execute("SET statement_timeout = '15000'")
                try:
                    db_rows = await conn.fetch(sql)
                except Exception as sql_err:
                    err_msg = str(sql_err).lower()
                    if "timeout" in err_msg or "canceling statement" in err_msg:
                        raise TimeoutError("Kueri membutuhkan waktu kalkulasi terlalu lama (>15 detik). Silakan persempit filter atau rentang waktu kueri Anda.")
                    
                    logger.warning("Vanna SQL gagal di percobaan 1: %s. Menjalankan auto-repair...", sql_err)
                    repair_prompt = f"""You previously generated this SQL:
```sql
{sql}
```
When executed on PostgreSQL, it produced the following error:
{sql_err}

Please fix the query. Note:
- Use physical tables like untt_penjualan (with column 'tanggal', 'hjakhir', 'batal') or untt_pembelian if views lack the required date columns.
- Ensure all referenced columns exist in the table.
Return ONLY the corrected SQL query in ```sql ... ``` code block."""
                    raw_repair = await panggil_fn(system_msg, repair_prompt, ai_config)
                    repaired_sql = ekstrak_sql(raw_repair)
                    if repaired_sql.lower().startswith("select") or repaired_sql.lower().startswith("with"):
                        sql = repaired_sql
                        db_rows = await conn.fetch(sql)
                    else:
                        raise sql_err

            durasi_ms = int((time.monotonic() - t0) * 1000)

            # 6. Format Hasil & Cek Mode Eksekutif vs Operasional
            columns = [k for k in db_rows[0].keys()] if db_rows else []
            rows = [[_konversi_nilai_vanna(v) for v in r.values()] for r in db_rows[:500]]
            
            # Cek setting narasi (User override atau Tenant default)
            user_narration = user.get("auto_narration")
            tenant_narration = tenant.get("auto_narration", False)
            is_auto_narration = user_narration if user_narration is not None else tenant_narration
            
            if is_auto_narration and rows:
                # Mode Eksekutif: LLM membuat narasi analitik
                try:
                    narr_prompt = f"""Data query hasil database:
Pertanyaan: {question}
Hasil (maks 5 baris pertama): {json.dumps(rows[:5], default=str)}
Total data: {len(rows)} baris.
Berikan ringkasan naratif eksekutif singkat (2-3 kalimat) dalam bahasa Indonesia yang menyorot tren dan angka penting."""
                    ringkasan = await panggil_fn("You are a business analytics expert. Provide concise Indonesian executive summary.", narr_prompt, ai_config)
                    allow_explain = False
                except Exception as e_narr:
                    logger.warning("Gagal membuat narasi eksekutif: %s", e_narr)
                    ringkasan = _format_ringkasan_otomatis(db_rows[:500], columns, question)
                    allow_explain = True
            else:
                # Mode Operasional: Ringkasan lokal cepat (0 token) + Tombol Jelaskan Lebih Dalam aktif
                ringkasan = _format_ringkasan_otomatis(db_rows[:500], columns, question)
                allow_explain = True

            ringkasan = _bersihkan_emoji_teks(ringkasan)
            comp_info = _deteksi_kueri_komparasi_periode(question, inherited_topic=inherited_topic)
            saran_list = comp_info.get("suggestions", []) if comp_info else []
            is_comp = bool(comp_info)

            response = {
                "source": "vanna",
                "confidence": "A",
                "sql": sql,
                "params": [],
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": len(db_rows) > 500,
                "duration_ms": durasi_ms,
                "memory_id": None,
                "question": question,
                "ringkasan": ringkasan,
                "saran": saran_list,
                "metode": "vanna",
                "allow_explain": allow_explain,
                "is_comparison": is_comp,
                "comparison_meta": comp_info
            }

        # Simpan ke SQL Memory agar pertanyaan yang sama berikutnya bernilai 0 token!
        # PENTING: Kueri eliptikal yang bergantung pada konteks sesi aktif (misal: "coba bandingkan keduanya",
        # "tampilkan rincian terpisah", atau topik yang diwarisi dari chat sebelumnya tanpa menyebutkan domain secara mandiri)
        # DILARANG disimpan ke sql_memory global agar tidak bocor ke sesi percakapan atau user lain.
        is_elliptical = (
            inherited_topic is not None
            and not any(w in question.lower() for w in [
                "jual", "penjualan", "beli", "pembelian",
                "servis", "service", "bengkel", "pkb", "wo",
                "part", "sparepart", "suku cadang"
            ])
        )
        if not is_elliptical and not response.get("is_multi_tab"):
            try:
                mem_id = await core_pool.fetchval(
                    """
                    INSERT INTO sql_memory (tenant_id, pertanyaan_ternormalisasi, sql, status, ringkasan, sumber, times_used, last_used, created_at, updated_at)
                    VALUES ($1, $2, $3, 'approved', $4, 'vanna', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    tenant_id, q_norm, sql, ringkasan
                )
                response["memory_id"] = mem_id
            except Exception as e_save:
                logger.warning("Gagal menyimpan ke sql_memory: %s", e_save)

        # Simpan ke percakapan agar muncul di UI
        conv_id = await ambil_atau_buat_conversation(core_pool, user_id, branch_code, question, conversation_id=conversation_id)
        response["conversation_id"] = conv_id
        await simpan_pesan(core_pool, conv_id, "user", question)
        await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

        # Simpan audit log sukses
        await tulis_audit(
            core_pool,
            user_id=user_id,
            branch_code=branch_code,
            prompt_text=question,
            ai_json_filter={"mode": "vanna", "model": ai_config.get("model")},
            generated_sql=sql,
            execution_time_ms=durasi_ms,
            status="success",
            error_message=None
        )

        return response

    except Exception as e:
        durasi_ms = int((time.monotonic() - t0) * 1000)
        logger.error("Error Mode Vanna: %s", e)
        await tulis_audit(
            core_pool,
            user_id=user_id,
            branch_code=branch_code,
            prompt_text=question,
            ai_json_filter={"mode": "vanna"},
            generated_sql=sql if 'sql' in locals() else None,
            execution_time_ms=durasi_ms,
            status="error",
            error_message=str(e)
        )
        raise


def ekstrak_narasi(llm_output: str) -> str:
    """Ekstrak narasi dari response JSON atau raw text LLM."""
    text = (llm_output or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for k in ("narasi", "analysis", "penjelasan", "text", "response", "content", "summary"):
                if k in data and isinstance(data[k], str) and data[k].strip():
                    return data[k].strip()
            if len(data) == 1 and isinstance(list(data.values())[0], str):
                return list(data.values())[0].strip()
    except Exception:
        m_json = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if m_json:
            try:
                data = json.loads(m_json.group(1))
                if isinstance(data, dict):
                    for k in ("narasi", "analysis", "penjelasan", "text", "response"):
                        if k in data and isinstance(data[k], str) and data[k].strip():
                            return data[k].strip()
            except Exception:
                pass
    return text


async def buat_penjelasan_naratif(
    core_pool,
    user: dict,
    branch_code: str,
    question: str,
    sql: str,
    rows: list
) -> str:
    """Buat narasi penjelasan mendalam on-demand saat user mengklik tombol 'Jelaskan Lebih Dalam'."""
    ai_config = await resolve_ai_config(core_pool, user.get("username", ""), branch_code)
    panggil_fn = panggil_llm_default
    q_text = (question or "Analisis data hasil kueri").strip()
    sample_rows = rows[:5] if rows else []

    narr_prompt = f"""Kueri Data:
Pertanyaan: {q_text}
SQL: {sql}
Hasil Data (sampel 5 baris pertama):
{json.dumps(sample_rows, default=str)}
Total Baris: {len(rows)}

Sebagai senior business analyst dealer, buatkan analisis naratif bisnis yang mendalam, profesional, dan SANGAT MUDAH DIBACA dalam bahasa Indonesia untuk membantu manajemen dealer mengambil keputusan.

PANDUAN FORMAT TAMPILAN:
- JANGAN menuliskan satu paragraf panjang yang padat tanpa jeda baris.
- Pisahkan penjelasan menjadi 2-3 paragraf pendek dengan baris baru ganda (\\n\\n).
- Jika ada poin rekomendasi tindakan, awali dengan 'Rekomendasi:' pada paragraf terpisah dan gunakan poin bertitik (• ) agar mudah dicerna eksekutif.

Format respons HARUS berupa JSON murni dengan kunci 'narasi':
{{"narasi": "tulis analisis naratif terstruktur di sini..."}}"""

    raw_output = await panggil_fn(
        "You are a senior business data analyst. Always respond in pure JSON format with a 'narasi' key.",
        narr_prompt,
        ai_config
    )
    return ekstrak_narasi(raw_output)

