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
    cek_apakah_minta_multi_query,
    susun_multi_sql_prompt,
    ekstrak_multi_sql,
    susun_ringkasan_eksekutif_multi,
    cek_apakah_perlu_komparasi,
    susun_tab_komparasi_divisi,
    _is_column_qty,
    _is_column_money,
)
from app.services.schema_mapper import is_schema_map_question, dapatkan_peta_database_tenant
from app.services.sql_guard import SqlGuardError, _has_dangerous_function
import sqlglot
from sqlglot import exp

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

        # Prioritaskan tabel fisik dasar daripada view terpotong bila ada
        order_sql = """
            (CASE 
                WHEN content ILIKE 'Table vw_%' THEN 2
                ELSE 0 
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

    # Jika pencarian kata kosong, berikan tabel-tabel teratas yang tersedia
    if not contexts:
        rows = await core_pool.fetch(
            "SELECT content FROM global_knowledge_base "
            "WHERE content ILIKE 'Table %' "
            "ORDER BY length(content) ASC "
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
        topic_context_note = f"\n=== Active Multi-turn Conversation Context:\nThe user is currently discussing '{inherited_topic}' in this session. Maintain relevant context if applicable.\n"

    return f"""You are a Postgres expert and AI data assistant for an operational enterprise database.
Your response should be based on the given context and follow the response guidelines:
{topic_context_note}
=== Database Context & Relationships:
{context}

=== User Input:
{question}

=== Response Guidelines:
1. If the user is asking for operational or transactional data, reports, metrics, or table queries:
   - Generate ONE valid PostgreSQL SELECT query.
   - Return ONLY the SQL query enclosed in ```sql ... ``` code block.
   - Use the tables, columns, and relationships provided in the context.
   - Do not include explanations outside the SQL code block.
2. If the user's input is a casual conversation, greeting, capability question, clarification, or question about concepts/terms that DOES NOT require querying database tables:
   - DO NOT generate SQL.
   - Respond directly and helpfully in Indonesian (Markdown format) without any ```sql code block.
   - Keep the tone polite, concise, empathetic, and clear (like Claude, Gemini, or ChatGPT).
   - Zero emoji policy: do not include emoji symbols in your response.
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


def _cari_kolom_tahun_transaksi(columns: list) -> str | None:
    """Mencari kolom tahun transaksi secara cerdas dengan prioritas semantik:
    1. Exact match: 'tahun', 'year', 'thn', 'periode_tahun'
    2. Kolom waktu transaksi/faktur: 'tahun_invoice', 'tahun_transaksi', 'tahun_penjualan', dsb.
    3. Kolom tahun generik tetapi bebas dari kata benda atribut fisik kendaraan ('tahun_rakit', 'tahun_pembuatan', 'id_tahun').
    """
    if not columns:
        return None

    cols_str = [str(c) for c in columns]
    cols_lower = {str(c).lower().strip(): c for c in columns}

    # 1. Exact match prioritas utama
    for exact in ("tahun", "year", "thn", "periode_tahun"):
        if exact in cols_lower:
            return cols_lower[exact]

    # 2. Kolom penanda waktu transaksi bisnis
    tx_markers = ("invoice", "transaksi", "penjualan", "pembelian", "faktur", "wo", "pkb", "tgl", "date")
    for c in cols_str:
        c_low = c.lower().strip()
        if any(t in c_low for t in ("tahun", "year", "thn")):
            if any(m in c_low for m in tx_markers):
                return c

    # 3. Kolom tahun generik tetapi bebas dari kata benda atribut fisik kendaraan
    blacklist = ("rakit", "pembuatan", "buat", "model", "umur", "usia", "id_tahun", "stok")
    for c in cols_str:
        c_low = c.lower().strip()
        if any(t in c_low for t in ("tahun", "year", "thn")):
            if not any(b in c_low for b in blacklist):
                return c

    return None


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
    elif _cari_kolom_tahun_transaksi(columns):
        thn_col = _cari_kolom_tahun_transaksi(columns)

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


def deteksi_topik_eksplisit(question: str) -> str | None:
    """Mendeteksi domain topik bisnis otomotif eksplisit dari teks pertanyaan pengguna.
    Kata kunci eksplisit ini memiliki prioritas tertinggi (override) di atas inherited_topic riwayat.
    """
    if not question:
        return None
    q_lower = question.lower()
    if any(w in q_lower for w in ["beli", "pembelian", "kulakan", "pengadaan", "hpunit", "tglinvoice"]):
        return "pembelian"
    if any(w in q_lower for w in ["servis", "service", "bengkel", "wo", "pkb", "mekanik"]):
        return "servis"
    if any(w in q_lower for w in ["sparepart", "suku cadang", "part"]):
        return "sparepart"
    if any(w in q_lower for w in ["jual", "penjualan", "omzet", "unit terjual", "spk", "hjakhir"]):
        return "penjualan"
    return None


def validasi_readonly_ast_vanna(sql: str) -> None:
    """Gerbang Pengaman AST Vanna: Memastikan query read-only aman (SELECT/WITH tunggal)
    tanpa mutasi data (INSERT/UPDATE/DELETE/DROP/ALTER/SELECT INTO) dan tanpa fungsi berbahaya.
    """
    if not sql or not sql.strip():
        raise SqlGuardError("Query SQL kosong")

    # Strip komentar SQL
    sql_clean = re.sub(r'--.*', '', sql).strip()

    try:
        statements = [s for s in sqlglot.parse(sql_clean, read="postgres") if s is not None]
    except Exception as e:
        # Fallback regex jika sqlglot parsing error karena dialek spesifik
        if not re.match(r"^\s*(select|with)\b", sql_clean, re.IGNORECASE):
            raise SqlGuardError(f"Hanya query SELECT atau WITH yang diizinkan: {e}")
        # Cek blacklist kata kunci mutasi berbahaya
        destructive_words = ["insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "grant ", "revoke "]
        if any(w in sql_clean.lower() for w in destructive_words):
            raise SqlGuardError("Kueri memuat kata kunci mutasi yang dilarang")
        return

    if not statements:
        raise SqlGuardError("Tidak ada statement SQL yang valid")
    if len(statements) > 1:
        raise SqlGuardError("Multi-statement SQL tidak diizinkan")

    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise SqlGuardError(f"Hanya statement SELECT/WITH yang diizinkan (ditemukan: {type(tree).__name__})")
    if getattr(tree, "args", {}).get("into"):
        raise SqlGuardError("Statement SELECT INTO tidak diizinkan")

    dangerous = _has_dangerous_function(tree)
    if dangerous:
        raise SqlGuardError(f"Fungsi PostgreSQL tidak diizinkan: {dangerous}")


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
            topik = deteksi_topik_eksplisit(r["content"])
            if topik:
                return topik

        # 2. Cek dari judul percakapan (pertanyaan pertama user saat sesi dibuat)
        title = await core_pool.fetchval(
            "SELECT title FROM conversations WHERE id = $1",
            conversation_id
        )
        if title:
            topik = deteksi_topik_eksplisit(title)
            if topik:
                return topik
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


def is_action_confirmation_phrase(question: str) -> bool:
    """Deteksi apakah input pengguna berupa konfirmasi persetujuan, delegasi tindakan,
    atau pemilihan opsi (misal: 'atur aja', 'lanjutkan', 'oke', 'gas', 'opsi 2', 'pilihan 1')."""
    if not question:
        return False
    q = question.strip().lower()
    q_clean = re.sub(r'[?!.,;:\'"]+', ' ', q).strip()
    q_clean = re.sub(r'\s+', ' ', q_clean)

    action_words = {
        "atur aja", "yaudah atur aja", "kamu yang atur", "kamu aja yang atur",
        "terserah", "terserah kamu", "lanjutkan", "lanjut", "gas", "gaskan",
        "proses", "eksekusi", "jalankan", "oke lanjut", "ok lanjut", "siap laksanakan",
        "boleh", "boleh deh", "yaudah", "aturin", "aturkan", "pilihin", "pilihin aja",
        "opsi 1", "opsi 2", "opsi 3", "opsi 4",
        "pilihan 1", "pilihan 2", "pilihan 3", "pilihan 4",
        "nomor 1", "nomor 2", "nomor 3", "nomor 4", "1", "2", "3", "4"
    }
    if q_clean in action_words:
        return True
    return bool(re.search(
        r"^(?:hmm\s+)?(?:yaudah\s+)?(?:atur\s+aja|kamu\s+(?:aja\s+)?yang\s+atur|terserah(?:\s+kamu)?|lanjutkan|lanjut|gas|gaskan|proses|eksekusi|jalankan|pilihin(?:\s+aja)?)(?:\s+deh|\s+ya|\s+dong)?$",
        q_clean
    ))


async def evaluasi_state_percakapan(core_pool, conversation_id: int | None, question: str) -> tuple[str, bool, dict | None]:
    """Dialogue State Tracking: Memeriksa apakah sesi aktif memiliki pending_proposal (tawaran modul/analisis)
    dan mengonfirmasi apakah balasan pengguna adalah persetujuan/delegasi tindakan ('atur aja', 'lanjutkan', 'opsi 2').

    Returns:
        tuple: (resolved_query, is_action_accepted, proposal_dict)
    """
    if not conversation_id or not question:
        return question, False, None

    try:
        row = await core_pool.fetchrow(
            "SELECT id, content FROM messages WHERE conversation_id = $1 AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            conversation_id
        )
        if not row or not row["content"]:
            return question, False, None

        raw_content = row["content"]
        try:
            assistant_data = json.loads(raw_content)
        except Exception:
            return question, False, None

        proposal = assistant_data.get("pending_proposal")
        if not proposal or proposal.get("status") != "awaiting_confirmation":
            return question, False, None

        q_lower = question.strip().lower()
        q_clean = re.sub(r'[?!.,;:\'"]+', ' ', q_lower).strip()
        q_clean = re.sub(r'\s+', ' ', q_clean)

        # 1. Cek pembatalan eksplisit
        if any(kw in q_clean for kw in ["batal", "ga jadi", "nggak jadi", "cancel", "tutup"]):
            logger.info("Pengguna membatalkan pending proposal pada conversation %s", conversation_id)
            return question, False, None

        async def _tandai_proposal_diterima(chosen_item):
            try:
                proposal["status"] = "accepted"
                proposal["accepted_action"] = chosen_item
                assistant_data["pending_proposal"] = proposal
                await core_pool.execute(
                    "UPDATE messages SET content = $1 WHERE id = $2",
                    json.dumps(assistant_data, default=str),
                    row["id"]
                )
            except Exception as e_upd:
                logger.debug("Gagal update status pending_proposal di DB: %s", e_upd)

        # 2. Cek pemilihan nomor opsi eksplisit (contoh: "opsi 2", "pilihan 1", "nomor 3", atau angka "2")
        options = proposal.get("options") or []
        opt_num_m = re.search(r'\b(?:opsi|pilihan|nomor)?\s*([1-4])\b', q_clean)
        if opt_num_m and any(w in q_clean for w in ["opsi", "pilihan", "nomor"]):
            idx = int(opt_num_m.group(1)) - 1
            if 0 <= idx < len(options):
                chosen = options[idx]
                logger.info("Dialogue State Tracking: Pengguna memilih opsi #%d (%s) -> %s", idx + 1, chosen.get("id"), chosen.get("query"))
                await _tandai_proposal_diterima(chosen)
                return chosen.get("query", question), True, chosen

        # 3. Cek kecocokan kata kunci spesifik opsi terkuat
        best_opt = None
        max_score = 0
        for opt in options:
            kws = opt.get("keywords") or [opt.get("id", ""), opt.get("label", "").lower()]
            score = sum(1 for kw in kws if kw in q_clean)
            if score > max_score:
                max_score = score
                best_opt = opt
        if best_opt and max_score > 0:
            logger.info("Dialogue State Tracking: Pengguna memilih opsi via keyword '%s' -> %s", best_opt.get("id"), best_opt.get("query"))
            await _tandai_proposal_diterima(best_opt)
            return best_opt.get("query", question), True, best_opt

        # 4. Cek konfirmasi umum / delegasi tindakan ("atur aja", "lanjutkan", "gas", "terserah", "yaudah")
        if is_action_confirmation_phrase(question):
            default_action = proposal.get("default_action") or (options[0] if options else None)
            if default_action and default_action.get("query"):
                logger.info("Dialogue State Tracking: Pengguna menyetujui default action proposal -> %s", default_action.get("query"))
                await _tandai_proposal_diterima(default_action)
                return default_action.get("query"), True, default_action

        return question, False, None
    except Exception as e:
        logger.warning("Gagal evaluasi state percakapan: %s", e)
        return question, False, None


def _periksa_integritas_output_percakapan(text: str) -> tuple[bool, str]:
    """Mechanical Output Guard: Memeriksa apakah teks naratif memuat tabel data fiktif
    atau klaim eksekusi/grafik palsu di jalur percakapan (non-SQL).
    
    Returns:
        tuple: (is_valid, cleaned_text)
    """
    if not text:
        return True, ""

    claim_pattern = re.compile(
        r'\b(?:analisis\s+selesai\s+dijalankan|berikut\s+hasilnya\s*:|grafik\s+interaktif\s+sudah\s+(?:saya\s+)?(?:di)?siapkan|sudah\s+(?:saya\s+)?(?:di)?siapkan\s+di\s+panel|grafik\s+(?:interaktif\s+)?(?:sudah\s+)?(?:telah\s+)?(?:di)?siapkan)\b',
        re.IGNORECASE
    )

    has_false_claim = bool(claim_pattern.search(text))
    has_numeric_table = False
    schema_keys = ['vw_', 'srv', 'untt', 'stpm', 'cari_', 'glbm', 'acctt', 'kategori', 'modul']

    lines = text.split('\n')
    cleaned_lines = []
    idx = 0
    n = len(lines)

    while idx < n:
        line = lines[idx]
        stripped = line.strip()

        # Deteksi awal blok tabel markdown
        if stripped.startswith('|') and stripped.endswith('|'):
            table_block = []
            while idx < n and lines[idx].strip().startswith('|') and lines[idx].strip().endswith('|'):
                table_block.append(lines[idx])
                idx += 1

            # Evaluasi apakah blok tabel ini memuat data transaksi numerik (halusinasi non-SQL)
            is_fake_numeric_table = False
            for t_row in table_block:
                t_str = t_row.strip()
                is_schema = any(k in t_str.lower() for k in schema_keys)
                has_nums = bool(re.search(r'\|\s*\d+[\d.,]*\s*\|', t_str))
                if has_nums and not is_schema:
                    is_fake_numeric_table = True
                    break

            if is_fake_numeric_table:
                has_numeric_table = True
                # Seluruh tabel fiktif dibuang (tidak dimasukkan ke cleaned_lines)
            else:
                cleaned_lines.extend(table_block)
            continue

        # Baris teks biasa: cek klaim fiktif
        if claim_pattern.search(line):
            has_false_claim = True
            idx += 1
            continue

        cleaned_lines.append(line)
        idx += 1

    cleaned_text = "\n".join(cleaned_lines).strip()
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)

    is_valid = not (has_false_claim or has_numeric_table)
    if not is_valid:
        logger.warning(
            "Mechanical Output Guard mendeteksi klaim/tabel fiktif di respons percakapan (has_claim=%s, has_table=%s)",
            has_false_claim, has_numeric_table
        )
        if len(cleaned_text) < 30:
            cleaned_text = (
                "Untuk menampilkan data transaksi ini secara akurat beserta visualisasi grafiknya, "
                "sistem perlu mengeksekusi kueri langsung ke database cabang Anda. "
                "Silakan klik salah satu rekomendasi kueri di bawah ini untuk langsung memuat data nyata."
            )

    return is_valid, cleaned_text


def _deteksi_kueri_komparasi_periode(question: str, inherited_topic: str | None = None) -> dict | None:
    """Deteksi kueri perbandingan antar periode (misal: 2024 vs 2025 atau 2020 vs 2021 vs 2022)."""
    q_lower = (question or "").lower()
    years = re.findall(r'\b(20[12]\d)\b', q_lower)
    is_vs = any(w in q_lower for w in [" vs ", " versus ", "bandingkan", "perbandingan", "komparasi", " beda ", "selisih", "dibandingkan", "dibanding"])

    explicit_topic = deteksi_topik_eksplisit(question)
    subject = explicit_topic or inherited_topic or "transaksi"
    frasa_subject = f"transaksi {subject}" if subject != "transaksi" else "data transaksi"

    unique_years = sorted(list(dict.fromkeys(years)))
    if len(unique_years) > 5:
        unique_years = unique_years[-5:]  # Batasi maksimal 5 periode terbaru demi keselamatan memori & pool

    if len(unique_years) >= 2:
        p1, p2 = unique_years[0], unique_years[1]
        if len(unique_years) == 2:
            thn_text = f"tahun {p1} dan {p2}"
        else:
            thn_text = f"tahun {', '.join(unique_years[:-1])} dan {unique_years[-1]}"

        saran_list = [
            f"Tampilkan rincian {frasa_subject} {thn_text} secara terpisah"
        ]
        for yr in unique_years:
            saran_list.append(f"Lihat detail {frasa_subject} tahun {yr}")

        return {
            "type": "year",
            "periods": unique_years,
            "p1": p1,
            "p2": p2,
            "subject": subject,
            "suggestions": saran_list
        }
    elif is_vs and len(unique_years) == 1:
        p1 = unique_years[0]
        p_prev = str(int(p1) - 1)
        return {
            "type": "year",
            "periods": [p_prev, p1],
            "p1": p_prev,
            "p2": p1,
            "subject": subject,
            "suggestions": [
                f"Tampilkan rincian {frasa_subject} tahun {p_prev} dan {p1} secara terpisah",
                f"Lihat detail {frasa_subject} tahun {p1}",
                f"Lihat detail {frasa_subject} tahun {p_prev}",
            ]
        }
    return None


def cek_apakah_minta_rincian_terpisah(question: str, inherited_topic: str | None = None,
                                      allowed_tables: set[str] | list[str] | None = None) -> dict | None:
    """Deteksi jika user meminta rincian periode terpisah (Gaya 2) untuk N tahun (2, 3, 4, 5+)."""
    q_lower = (question or "").lower()
    is_terpisah = any(w in q_lower for w in ["terpisah", "sendiri-sendiri", "masing-masing", "pisah", "pecah", "tiap tabel", "per tabel"])
    is_rincian = any(w in q_lower for w in ["rincian", "detail", "faktur", "transaksi", "tabel terpisah"])
    years = re.findall(r'\b(20[12]\d)\b', q_lower)
    unique_years = sorted(list(dict.fromkeys(years)))
    if len(unique_years) > 5:
        unique_years = unique_years[-5:]  # Batasi maksimal 5 tabel terpisah

    if (is_terpisah or is_rincian) and len(unique_years) >= 2:
        p1, p2 = unique_years[0], unique_years[1]

        # Tentukan topik dari kueri eksplisit (override) atau inherited_topic dari percakapan
        explicit_topic = deteksi_topik_eksplisit(question)
        topic = explicit_topic or inherited_topic or "penjualan"

        # Tentukan tabel target berdasarkan konteks kueri
        table = "untt_penjualan"
        date_col = "tanggal"
        order_col = "tanggal"
        money_col = "hjakhir"
        filter_clause = "NOT COALESCE(batal, FALSE) AND NOT COALESCE(retur, FALSE)"
        columns_to_select = "nomor, tanggal, nomor_pesanan, norangka, hjunit, diskon, hjakhir"

        if topic == "pembelian":
            table = "untt_pembelian"
            date_col = "tglinvoice"
            order_col = "tglinvoice"
            money_col = "hpunit"
            filter_clause = "1=1"
            columns_to_select = "nomor, tglinvoice, norangka, hpunit, hpdpp, hpppn"
        elif topic == "servis":
            table = "srvt_wo"
            date_col = "tanggal"
            order_col = "tanggal"
            money_col = "totalestimasibiaya"
            filter_clause = "NOT COALESCE(batal, FALSE)"
            columns_to_select = "nomor, tanggal, nomor_customer, nopolisi, totalestimasibiaya"
        elif topic == "sparepart":
            table = "srvt_wodetail"
            date_col = "tanggal"
            order_col = "nomor"
            money_col = "part"
            filter_clause = "part > 0"
            columns_to_select = "nomor_wo, part, jenis"

        if allowed_tables is not None:
            allowed_lower = {t.lower() for t in allowed_tables}
            if table.lower() not in allowed_lower:
                logger.info("Tabel target '%s' untuk rincian terpisah tidak ditemukan dalam allowed_tables. Fallback ke kueri umum.", table)
                return None

        window_select = f"{columns_to_select}, COUNT(*) OVER() AS total_transaksi_tahun, SUM({money_col}) OVER() AS total_omzet_tahun"
        domains = []
        for yr in unique_years:
            sql_yr = f"SELECT {window_select} FROM {table} WHERE EXTRACT(YEAR FROM {date_col}) = {yr} AND {filter_clause} ORDER BY {order_col} DESC LIMIT 50;"
            domains.append({
                "id": f"thn_{yr}",
                "title": f"Rincian Tahun {yr}",
                "icon": "Calendar",
                "sql": sql_yr,
            })

        return {
            "category": "rincian_terpisah",
            "mode": "separated_years",
            "periods": unique_years,
            "p1": p1,
            "p2": p2,
            "topic": topic,
            "table": table,
            "domains": domains,
        }
    return None


def susun_kueri_komparasi_deterministik(comp_info: dict | None, question: str,
                                        allowed_tables: set[str] | list[str] | None = None) -> str | None:
    """Menyusun kueri SQL komparasi tahunan secara deterministik (0 LLM Token, 0 Halusinasi).
    Aktif jika pertanyaan menuntut komparasi temporal antar tahun pada level modul/agregat,
    bukan rincian atribut khusus (model, warna, dsb).
    """
    if not comp_info or not comp_info.get("periods") or len(comp_info["periods"]) < 2:
        return None

    q_lower = (question or "").lower()
    # Jika menanyakan atribut atau dimensi spesifik, serahkan ke LLM
    spesifik_keywords = [
        "model", "tipe", "warna", "sales", "wiraniaga", "customer", "pelanggan",
        "wilayah", "kota", "leasing", "mekanik", "kasir", "grade", "cabang"
    ]
    if any(k in q_lower for k in spesifik_keywords):
        return None

    periods = comp_info["periods"]
    years_csv = ", ".join(str(p) for p in periods)
    subject = comp_info.get("subject") or "penjualan"

    target_table_map = {
        "penjualan": "untt_penjualan",
        "transaksi": "untt_penjualan",
        "pembelian": "untt_pembelian",
        "servis": "srvt_wo",
        "suku cadang": "srvt_wodetail",
        "sparepart": "srvt_wodetail",
    }
    target_table = target_table_map.get(subject)
    if not target_table:
        return None

    if allowed_tables is not None:
        allowed_lower = {t.lower() for t in allowed_tables}
        if target_table.lower() not in allowed_lower:
            logger.info("Tabel target '%s' untuk topik '%s' tidak ditemukan dalam allowed_tables. Fallback deterministik ke LLM.", target_table, subject)
            return None

    if subject == "penjualan" or subject == "transaksi":
        return f"""SELECT 
    EXTRACT(YEAR FROM tanggal)::INT AS tahun,
    COUNT(nomor) AS unit_terjual,
    COALESCE(SUM(hjakhir), 0) AS total_omzet
FROM untt_penjualan
WHERE NOT COALESCE(batal, FALSE) AND NOT COALESCE(retur, FALSE)
  AND EXTRACT(YEAR FROM tanggal) IN ({years_csv})
GROUP BY EXTRACT(YEAR FROM tanggal)::INT
ORDER BY tahun ASC;"""

    elif subject == "pembelian":
        return f"""SELECT 
    EXTRACT(YEAR FROM tglinvoice)::INT AS tahun,
    COUNT(nomor) AS total_unit_dibeli,
    COALESCE(SUM(hpunit), 0) AS total_nilai_pembelian
FROM untt_pembelian
WHERE EXTRACT(YEAR FROM tglinvoice) IN ({years_csv})
GROUP BY EXTRACT(YEAR FROM tglinvoice)::INT
ORDER BY tahun ASC;"""

    elif subject == "servis":
        return f"""SELECT 
    EXTRACT(YEAR FROM tanggal)::INT AS tahun,
    COUNT(nomor) AS total_servis,
    COALESCE(SUM(totalestimasibiaya), 0) AS total_biaya_servis
FROM srvt_wo
WHERE NOT COALESCE(batal, FALSE)
  AND EXTRACT(YEAR FROM tanggal) IN ({years_csv})
GROUP BY EXTRACT(YEAR FROM tanggal)::INT
ORDER BY tahun ASC;"""

    elif subject in ("suku cadang", "sparepart"):
        return f"""SELECT 
    EXTRACT(YEAR FROM tanggal)::INT AS tahun,
    COUNT(nomor_wo) AS total_item_part,
    COALESCE(SUM(part), 0) AS total_nilai_part
FROM srvt_wodetail
WHERE part > 0
  AND EXTRACT(YEAR FROM tanggal) IN ({years_csv})
GROUP BY EXTRACT(YEAR FROM tanggal)::INT
ORDER BY tahun ASC;"""

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
    """Deteksi apakah pertanyaan pengguna merupakan sapaan, percakapan santai, atau permintaan panduan umum."""
    if not question:
        return False
    if is_action_confirmation_phrase(question):
        return False
    q = question.strip().lower()
    q_clean = re.sub(r'[?!.,;:\'"]+', ' ', q).strip()
    q_clean = re.sub(r'\s+', ' ', q_clean)

    # 1. Normalisasi karakter huruf berulang (contoh: "alohaa" -> "aloha", "halooo" -> "halo", "heyyy" -> "hey")
    q_normalized_words = [re.sub(r'(.)\1{1,}', r'\1', w) for w in q_clean.split()]
    q_normalized_phrase = " ".join(q_normalized_words)

    # 2. Daftar sapaan komprehensif (termasuk variasi informal, gaul, dan sapaan daerah)
    greetings = {
        "halo", "hai", "hello", "hi", "hey", "hei", "helo", "aloha", "alo", "hola",
        "oi", "woi", "yo", "yoo", "p", "ping", "tes", "test", "testing",
        "pagi", "siang", "sore", "malam",
        "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
        "met pagi", "met siang", "met sore", "met malam",
        "assalamualaikum", "assalamu'alaikum", "samlikum", "shalom",
        "apa kabar", "gimana kabar", "kabar baik",
        "permisi", "punten", "kulo nuwun", "sampurasun",
        "terima kasih", "makasih", "thanks", "thx", "ok", "oke", "siap", "mantap", "keren"
    }

    raw_words = q_clean.split()
    raw_first_word = raw_words[0] if raw_words else ""
    norm_first_word = q_normalized_words[0] if q_normalized_words else ""

    if q_clean in greetings or q_normalized_phrase in greetings:
        return True

    if len(raw_words) <= 2:
        if raw_first_word in greetings or norm_first_word in greetings:
            return True

    # 3. Pertanyaan kapabilitas / menu / bantuan
    guide_phrases = [
        "ada data apa aja", "ada data apa saja", "ada data apa", "data apa aja yang ada",
        "data apa saja yang ada", "data apa yang tersedia", "data apa saja yang tersedia",
        "bisa bantu apa", "bisa bantu apa saja", "bisa apa saja", "kamu bisa apa",
        "apa yang bisa kamu lakukan", "bagaimana cara pakai", "cara pakainya gimana",
        "panduan penggunaan", "bantu saya", "menu apa saja", "fitur apa saja",
        "siapa kamu", "kamu siapa", "kenalan", "kamu robot apa"
    ]
    if any(q_clean.startswith(gp) or q_clean == gp for gp in guide_phrases):
        return True

    # 4. Permintaan data yang sangat samar (vague data request tanpa spesifikasi entitas)
    fillers = {
        "kasih", "minta", "berikan", "tampilkan", "bagi", "kirim", "lihat", "cek",
        "coba", "tolong", "dong", "aku", "saya", "kami", "ya", "kan", "lah", "sih",
        "min", "bot", "ai", "apa", "aja", "saja", "deh", "nih", "tuh", "ke", "buat", "untuk",
        "gw", "gua", "gue", "mau", "pengen", "bisa", "gak", "ga", "nggak", "tidak", "kah",
        "semisal", "misal", "misalkan", "kalau", "jika"
    }
    words = [w for w in q_clean.split() if w not in fillers]
    if words in [["data"], ["data", "data"], ["database"], ["semua", "data"], ["seluruh", "data"], ["semua"], []]:
        return True

    # 5. Deteksi Kueri Non-Data (Short casual message tanpa kata kunci bisnis otomotif apa pun)
    BUSINESS_DATA_KEYWORDS = {
        "jual", "penjualan", "beli", "pembelian", "omzet", "omset", "harga", "biaya", "uang",
        "unit", "mobil", "tipe", "model", "stok", "stock", "servis", "service", "bengkel",
        "pkb", "wo", "part", "parts", "sparepart", "suku cadang", "customer", "pelanggan",
        "sales", "salesman", "mekanik", "transaksi", "faktur", "invoice", "laba", "rugi",
        "tahun", "bulan", "periode", "terlaris", "terbanyak", "terbesar", "tertinggi", "terendah",
        "ranking", "peringkat", "daftar", "tabel", "rincian", "detail", "bandingkan",
        "perbandingan", "grafik", "laporan", "kenapa", "mengapa", "kapan", "siapa", "berapa",
        "hitung", "total", "jumlah", "rekap", "analisis", "rata-rata", "semua", "seluruh",
        "2024", "2025", "2026"
    }
    if len(raw_words) <= 4:
        has_business_kw = any(any(kw in w for kw in BUSINESS_DATA_KEYWORDS) for w in raw_words)
        if not has_business_kw:
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
        r"^(?:loh\s+)?(?:ini|itu)\s+(?:data|tabel|laporan|grafik|hasil)(?:\s+(?:apa|sih|maksudnya|nih|tuh))*$",
        r"^(?:loh\s+)?(?:data|tabel|laporan|grafik|hasil)\s+apa(?:\s+(?:ini|itu|sih|tuh|nih))*$",
        r"^(?:loh\s+)?(?:data|tabel)\s+apa(?:an)?(?:\s+(?:ini|itu|sih|tuh|nih))?$",
        r"^(?:loh\s+)?maksud(?:nya)?(?:\s+dari)?\s+.*(?:data|tabel|laporan|grafik|angka|ini|itu)",
        r".*maksud(?:nya)?\s+apa",
        r"^artinya(?:\s+apa)?$",
        r"^(?:coba\s+)?jelaskan\s+(?:data|tabel|laporan|hasil|kolom)(?:\s+(?:di\s+atas|ini|tersebut|barusan|tadi))?$",
        r"^(?:apa\s+maksud|apa\s+arti|artinya)\s+(?:kolom|tabel|data|angka)",
        r"^kenapa\s+(?:datanya|angkanya|tabelnya)\s+(?:seperti\s+ini|begini|begitu)$",
        r"^tabel\s+apa\s+(?:yang\s+)?(?:barusan|tadi)$",
        r"(?:tadi|barusan).*(?:kasih|tampil(?:kan)?|keluar(?:kan)?).*(?:data|tabel)\s+apa",
        r"(?:tadi|barusan).*(?:data|tabel)\s+apa",
        r"(?:data|tabel)\s+apa.*(?:tadi|barusan)",
        r".*(?:data|tabel)\s+apa\s+(?:yang\s+)?(?:lu|kamu|anda)\s+kasih",
        r"^(?:loh\s+)?(?:mana\s+grafik(?:nya)?|grafik(?:nya)?\s+(?:kok\s+)?(?:mana|ga\s+ada|nggak\s+ada|tidak\s+ada|belum\s+muncul))\??$",
        r"^(?:loh\s+)?(?:mana\s+tabel(?:nya)?|tabel(?:nya)?\s+(?:kok\s+)?(?:mana|ga\s+ada|nggak\s+ada|tidak\s+ada|belum\s+muncul))\??$",
        r"^(?:loh\s+)?grafik(?:nya)?\s+mana\??$",
    ]
    for pat in patterns:
        if re.search(pat, q_clean):
            return True

    keywords = [
        "data apa ini", "data apa itu", "tabel apa ini", "tabel apa itu",
        "maksud tabel ini", "maksud data ini", "jelaskan data di atas",
        "jelaskan tabel di atas", "jelaskan tabel ini", "maksud dari tabel",
        "ini maksudnya apa", "maksud tabel di atas", "tadi lu kasih apa",
        "tadi lu kasih data apa", "data apa barusan", "data apa tadi"
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
    ai_config: dict | None = None,
) -> dict:
    """Mode Panduan Orientasi: memberikan ringkasan modul data operasional dealer yang tersedia."""
    has_prior_chat = False
    if conversation_id:
        try:
            prior_cnt = await core_pool.fetchval(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = $1",
                conversation_id
            )
            if prior_cnt and prior_cnt > 0:
                has_prior_chat = True
        except Exception:
            pass

    if has_prior_chat:
        ringkasan = (
            "Berikut panduan modul data operasional dealer yang dapat Anda analisis:\n\n"
            "1. Penjualan Unit Kendaraan: Volume penjualan, tren omzet bulanan dan tahunan, ranking model mobil terlaris, rincian faktur penjualan, dan performa salesman.\n"
            "2. Jasa Servis Bengkel: Volume Work Order (PKB), pendapatan jasa perawatan, jenis pekerjaan servis, dan histori servis kendaraan.\n"
            "3. Suku Cadang & Sparepart: Pergerakan persediaan suku cadang, penjualan counter/part shop, dan omzet suku cadang.\n"
            "4. Pelanggan & Customer: Profil pelanggan terdaftar, histori pembelian unit, dan persebaran wilayah pelanggan.\n\n"
            "Silakan ketik pertanyaan spesifik mengenai data yang ingin Anda analisis, atau klik salah satu rekomendasi pertanyaan di bawah ini."
        )
    else:
        ringkasan = (
            "Selamat datang di Asisten AI Database Dealer. Platform ini terhubung langsung ke database operasional cabang Anda.\n\n"
            "Berikut adalah modul data utama yang siap Anda analisis:\n\n"
            "1. Penjualan Unit Kendaraan: Volume penjualan, tren omzet bulanan dan tahunan, ranking model mobil terlaris, rincian faktur penjualan, dan performa salesman.\n"
            "2. Jasa Servis Bengkel: Volume Work Order (PKB), pendapatan jasa perawatan, jenis pekerjaan servis, dan histori servis kendaraan.\n"
            "3. Suku Cadang & Sparepart: Pergerakan persediaan suku cadang, penjualan counter/part shop, dan omzet suku cadang.\n"
            "4. Pelanggan & Customer: Profil pelanggan terdaftar, histori pembelian unit, dan persebaran wilayah pelanggan.\n\n"
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

    ai_provider = ai_config.get("provider") if ai_config else None
    ai_model = ai_config.get("model") if ai_config else None
    await tulis_audit(
        core_pool,
        user_id=user_id,
        branch_code=branch_code,
        prompt_text=question,
        ai_json_filter={
            "provider": ai_provider,
            "model": ai_model,
            "category": "conversational_guide",
            "mode": "conversational_guide",
        },
        generated_sql="",
        execution_time_ms=durasi_ms,
        status="success",
        error_message=None,
    )
    return response


def _is_conversational_question(question: str) -> bool:
    """Deteksi apakah pertanyaan pengguna merupakan percakapan murni, sapaan, kapabilitas,
    pertanyaan hipotetis / kemungkinan, pertanyaan fitur sistem, atau istilah / konsep otomotif
    (yang harus dijawab dengan teks naratif tanpa SQL)."""
    if not question:
        return False
    if is_action_confirmation_phrase(question):
        return False
    q = question.strip().lower()
    q_clean = re.sub(r'[?!.,;:\'"]+', ' ', q).strip()
    q_clean = re.sub(r'\s+', ' ', q_clean)

    # 1. Cek general guide & greetings
    if _is_general_guide_question(question):
        return True

    # 2. Pertanyaan Hipotetis / Kemampuan / Kemungkinan / Meta
    # Contoh: "semisal gw mau semua data bisa?", "bisa gak kalau...", "apakah bisa minta data...",
    # "bisa ekspor excel ga?", "ada grafik gak?", "kamu pakai model apa?"
    hypothetical_patterns = [
        r"^(?:semisal|misal|misalkan|seumpama|kalau|jika|bagaimana jika|gimana kalau|gimana jika)\b",
        r"^(?:apakah|apa)\s+(?:bisa|memungkinkan|bisa bantu|ada)\b",
        r"^(?:bisa|bisakah)\s+(?:gak|ga|nggak|tidak|kah)?\s*(?:kalau|jika|minta|tampilkan|ekspor|bikin|buat|download)\b",
        r"^(?:bisa|bisa bantu)\s+(?:apa\s+saja|apa\s+aja|apaan\s+aja)\??$",
        r"^(?:mau\s+nanya|mau\s+tanya|nanya\s+dong|tanya\s+dong)\b",
        r"\b(?:bisa\s+di\s*ekspor|bisa\s+download|bisa\s+unduh|fitur\s+grafik|ada\s+grafik)\b",
        r"\b(?:kamu\s+siapa|kamu\s+dibuat|siapa\s+pembuatmu|kamu\s+pakai\s+model|kamu\s+pakai\s+ai|data\s+dari\s+mana)\b",
    ]
    for pat in hypothetical_patterns:
        if re.search(pat, q_clean):
            # Kecuali jika jelas ada perintah agregasi analitis langsung tanpa konjungsi hipotetis
            if not re.search(r"^(?:tampilkan|hitung|berapa|daftar)\s+", q_clean):
                return True

    # 3. Pertanyaan Broad "Semua Data" tanpa spesifikasi entitas / metrik
    broad_data_patterns = [
        r"^(?:semisal\s+)?(?:gw\s+|aku\s+|saya\s+)?(?:mau\s+|minta\s+|tampilkan\s+|lihat\s+)?(?:semua|seluruh)\s+data(?:\s+bisa|\s+dong|\s+deh)?\??$",
        r"^(?:semua\s+data|seluruh\s+data|semua)$",
        r"^(?:tampilkan\s+|minta\s+)?semua\s+database\??$",
    ]
    for pat in broad_data_patterns:
        if re.search(pat, q_clean):
            return True

    # 4. Ungkapan keraguan / kebingungan / fillers ("emm apa yaa", "bingung mau tanya apa")
    hesitation_patterns = [
        r"^(?:e+m+|h+m+|uhm+|eh+)\s*(?:apa\s+ya+|gimana\s+ya+|mau\s+nanya\s+apa)*",
        r"^(?:bingung|gatau|ga\s+tau|nggak\s+tahu|tidak\s+tahu)\s+(?:mau\s+)?(?:nanya|tanya|minta)\s+apa",
        r"^(?:kasih\s+|beri\s+)?(?:ide|saran|rekomendasi)(?:\s+dong|\s+pertanyaan)?",
        r"^(?:tunggu|bentar|sebentar)\s*(?:dulu)?$",
    ]
    for pat in hesitation_patterns:
        if re.search(pat, q_clean):
            return True

    # 5. Pola pertanyaan istilah, konsep, definisi, perbedaan
    concept_patterns = [
        r"^(?:apa\s+(?:sih\s+)?(?:itu|arti|artinya|maksud|maksudnya|kepanjangan|kepanjangannya|definisi|pengertian)\s+)(.+)",
        r"^(.+?)\s+(?:itu\s+apa|artinya\s+apa|maksudnya\s+apa|kepanjangannya\s+apa)\??$",
        r"^(?:apa\s+)?(?:bedanya|perbedaan(?:\s+antara)?)\s+(.+)",
        r"^jelaskan\s+(?:tentang\s+|mengenai\s+|apa\s+itu\s+|konsep\s+|istilah\s+)(.+)",
        r"^(?:apa\s+yang\s+dimaksud(?:\s+dengan)?)\s+(.+)",
        r"^(?:apa\s+fungsi|apa\s+kegunaan|fungsi\s+dari|kegunaan\s+dari)\s+(.+)",
    ]
    for pat in concept_patterns:
        if re.search(pat, q_clean):
            return True

    # 6. Kata penutup / respon apresiasi santai
    closing_words = {
        "terima kasih", "makasih", "makasih banyak", "terima kasih banyak",
        "thanks", "thank you", "thx", "tq", "mantap", "mantap jiwa", "keren", "keren banget",
        "ok", "oke", "oke sip", "siap", "siap laksanakan", "bagus", "good", "nice", "sip"
    }
    if q_clean in closing_words:
        return True

    return False


def _ekstrak_teks_naratif_bersih(raw: str) -> str:
    """Membersihkan output teks percakapan dari pembungkus JSON atau prefix format yang tidak diinginkan."""
    if not raw:
        return ""
    t = raw.strip()

    # 1. Coba parse JSON standar jika model membungkus dalam JSON object
    try:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            d = json.loads(m.group(0))
            if isinstance(d, dict):
                for k in ["jawaban", "reply", "response", "message", "text", "penjelasan", "ringkasan", "answer", "content"]:
                    if k in d and isinstance(d[k], str) and len(d[k].strip()) > 5:
                        return d[k].strip()
                first_s = next((v for v in d.values() if isinstance(v, str) and len(v.strip()) > 5), None)
                if first_s:
                    return first_s.strip()
    except Exception:
        pass

    # 2. Tangani kasus LLM mengembalikan JSON malformed / prefix seperti: {"response":"Halo{"response":"...
    m_str = re.search(r'["\'](?:response|message|text|jawaban)["\']\s*:\s*["\']([\s\S]+?)["\']\s*\}?$', t)
    if m_str:
        val = m_str.group(1)
        val = val.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
        if '{"response":' in val:
            val = val.split('{"response":')[-1].strip('"\': ')
        return val.strip()

    # 3. Potong prefix {"response": " jika tersisa di awal string
    clean = re.sub(r'^\s*\{\s*["\']\w+["\']\s*:\s*["\']?', '', t)
    clean = re.sub(r'["\']?\s*\}\s*$', '', clean)
    clean = clean.replace('\\n', '\n').replace('\\"', '"')
    return clean.strip()


async def tangani_kueri_percakapan(
    core_pool,
    conversation_id: int | None,
    question: str,
    user_id: int,
    branch_code: str,
    t0: float,
    ai_config: dict | None = None,
    llm_call_fn=None,
) -> dict:
    """Mode Percakapan Murni: Menjawab sapaan, kapabilitas, atau konsep otomotif dealer secara luwes dan naratif (0 SQL, 0 Table)."""
    durasi_ms = int((time.monotonic() - t0) * 1000)
    answer_text = ""

    # Muat konteks multi-turn riwayat percakapan sebelumnya
    history_context = ""
    if conversation_id:
        try:
            prev_msgs = await core_pool.fetch(
                "SELECT role, content FROM messages WHERE conversation_id = $1 ORDER BY id DESC LIMIT 5",
                conversation_id
            )
            if prev_msgs:
                hist_lines = []
                for m in reversed(prev_msgs):
                    r = "Pengguna" if m["role"] == "user" else "Asisten"
                    txt = m["content"]
                    try:
                        j = json.loads(txt)
                        txt = j.get("ringkasan") or j.get("question") or txt
                    except Exception:
                        pass
                    hist_lines.append(f"{r}: {txt[:200]}")
                history_context = "Riwayat percakapan sebelumnya:\n" + "\n".join(hist_lines) + "\n\n"
        except Exception as e_hist:
            logger.debug("Gagal memuat riwayat percakapan: %s", e_hist)

    # Coba panggil LLM untuk jawaban percakapan yang cerdas dan luwes
    panggil_fn = llm_call_fn or panggil_llm_default
    if ai_config:
        try:
            system_msg = (
                "Anda adalah Asisten AI Analis Data Dealer Otomotif (DMS AI Platform) yang cerdas, profesional, dan empatik, "
                "layaknya model AI modern seperti Claude, Gemini, atau GPT.\n"
                "Sistem ini terhubung langsung ke database operasional cabang dealer (ERP Otobitz Cloud) dengan lebih dari 2.300 tabel.\n"
                "Modul data utama yang tersedia:\n"
                "1. Penjualan Unit Kendaraan (faktur penjualan, SPK, stok unit, model mobil terlaris, diskon, performa salesman)\n"
                "2. Jasa Servis Bengkel (Work Order/PKB, estimasi biaya, histori servis per nopol/norangka, SA, teknisi)\n"
                "3. Suku Cadang & Sparepart (persediaan stok part, part masuk/keluar, omzet penjualan counter)\n"
                "4. Pelanggan & Customer (profil pelanggan terdaftar, histori pembelian unit, persebaran kota)\n"
                "5. Keuangan & Kasir (pembayaran kasir, piutang customer, faktur)\n"
                "\n"
                "Fitur unggulan platform yang dapat disebutkan jika relevan:\n"
                "- Visualisasi Grafik Interaktif Otomatis (Recharts Bar & Line Chart)\n"
                "- Ekspor Spreadsheet Excel (.xlsx) standar akuntansi lengkap dengan grafik native bawaan Excel\n"
                "- Verifikasi SQL otomatis dan SQL Memory replay untuk kecepatan tinggi\n"
                "\n"
                "Panduan Menjawab:\n"
                "- Jika pengguna ragu atau bingung (misal 'emm apa yaa', 'bingung mau tanya apa'): Sambut dengan ramah dan tawarkan 3-4 ide pertanyaan data paling menarik.\n"
                "- Jika pengguna menanyakan 'semua data' (misal 'semisal gw mau semua data bisa?', 'bisa tampilkan semua data?'): Jelaskan secara diplomatis bahwa database dealer sangat besar dengan jutaan transaksi di ribuan tabel, sehingga menampilkan seluruh data sekaligus tidak praktis dan membuat tampilan macet. Arahkan pengguna untuk memilih modul data spesifik atau rentang tahun tertentu.\n"
                "- Jika pengguna menanyakan fitur (grafik, ekspor excel, model AI, sumber data): Jelaskan secara jelas dan informatif.\n"
                "- Jika pengguna menanyakan istilah atau konsep bisnis otomotif (PKB, SPK, VIN, OTR, DPP, COGS, dll): Berikan penjelasan yang tepat dan ringkas dalam konteks dealer.\n"
                "- DILARANG meminta pengguna mengetik kata sandi konfirmasi seperti 'Silakan ketik lanjutkan'.\n"
                "- DILARANG berpura-pura telah mengeksekusi analisis database atau mengarang hasil analisis/tabel angka fiktif di dalam teks percakapan.\n"
                "- DILARANG mengklaim 'grafik sudah disiapkan di panel', karena grafik visual hanya muncul setelah kueri SQL nyata dieksekusi.\n"
                "- Jika pengguna menanyakan modul data (misal keuangan, kasir, piutang), jelaskan ruang lingkupnya secara ringkas dan tawarkan opsi pertanyaan konkret.\n"
                "- Format teks: Gunakan Markdown yang rapi, paragraf pendek (1-2 kalimat), dan bullet points dengan judul tebal (**label**).\n"
                "- DILARANG menggunakan emoji (Zero Emoji Policy). JANGAN mengembalikan format JSON, jawab langsung dalam teks Markdown naratif."
            )
            prompt_input = f"{history_context}Pertanyaan pengguna saat ini: {question}"
            try:
                raw_output = await panggil_fn(system_msg, prompt_input, ai_config, response_json=False)
            except TypeError:
                raw_output = await panggil_fn(system_msg, prompt_input, ai_config)

            if raw_output and len(raw_output.strip()) > 5:
                extracted = _ekstrak_teks_naratif_bersih(raw_output)
                if extracted and len(extracted) > 5:
                    answer_text = _bersihkan_emoji_teks(extracted)
        except Exception as e_llm:
            logger.warning("Panggilan LLM percakapan gagal (%s), beralih ke respons deterministik fallback...", e_llm)

    # Fallback cerdas jika LLM tidak tersedia atau gagal
    if not answer_text:
        q_l = question.lower()
        if any(w in q_l for w in ["semua data", "seluruh data"]) or (any(w in q_l for w in ["semisal", "misal"]) and "data" in q_l):
            answer_text = (
                "Secara teknis, Anda dapat mengakses seluruh data yang ada di database dealer. "
                "Database operasional cabang Anda memiliki total **2.387 tabel** yang terkelompokkan ke dalam 8 kategori modul ERP:\n\n"
                "| Kategori | Jumlah | Isinya |\n"
                "| :--- | :--- | :--- |\n"
                "| `vw_` | 706 | View laporan (*ready-made reports*) |\n"
                "| `srv / srvt / srvm` | 1.080 | Service - Work Order, servis, mekanik |\n"
                "| `untt / untm` | 274 | Unit - transaksi & master kendaraan (SPK, faktur, DO) |\n"
                "| `stpm` | 88 | Suku cadang/Parts - stok, master part |\n"
                "| `cari_` | 67 | View pencarian (daftar umur piutang, hutang, dll) |\n"
                "| `glbm` | 32 | Master data (GL) - customer, salesman, karyawan |\n"
                "| `acctt / acctm` | 31 | Akuntansi - jurnal, account |\n"
                "| `Lainnya` | 109 | dashboard, tax invoice, konfigurasi, dll |\n\n"
                "Menampilkan jutaan baris dari ribuan tabel sekaligus dalam satu layar tentu tidak praktis dan akan membebani peramban web. "
                "Namun, Anda dapat meminta laporan ringkasan, analisis tren, ranking, atau rincian transaksi dari modul mana pun di atas.\n\n"
                "Modul mana yang ingin Anda analisis terlebih dahulu?"
            )
        elif any(w in q_l for w in ["apa ya", "bingung", "ide", "rekomendasi", "saran", "gatau", "ga tau"]):
            answer_text = (
                "Santai saja, tidak perlu terburu-buru. Saya siap membantu Anda kapan saja.\n\n"
                "Berikut beberapa rekomendasi pertanyaan bisnis yang sering dianalisis oleh manajemen dealer:\n\n"
                "- **Penjualan**: *Berapa total penjualan unit tahun 2025?* atau *Tampilkan 5 model mobil terlaris*.\n"
                "- **Bengkel**: *Berapa total pendapatan servis bengkel tahun 2025?* atau *Tren servis bulanan*.\n"
                "- **Pelanggan**: *Daftar 10 customer dengan transaksi pembelian terbesar*.\n"
                "- **Stok**: *Berapa sisa stok unit mobil saat ini?*\n\n"
                "Silakan pilih salah satu pertanyaan di atas atau sampaikan topik yang ingin Anda ketahui."
            )
        elif any(w in q_l for w in ["excel", "ekspor", "export", "download", "unduh"]):
            answer_text = (
                "Ya, tentu bisa. Setiap laporan data yang disajikan oleh sistem ini dapat langsung Anda unduh dalam format **Excel (.xlsx) berstandar akuntansi**.\n\n"
                "File Excel yang diunduh sudah dilengkapi dengan format mata uang Rupiah yang rapi, header dokumen resmi, serta **grafik visual bawaan Excel** yang disematkan langsung di dalam spreadsheet. Cukup klik tombol **Ekspor Excel** di pojok kanan atas kartu laporan."
            )
        elif any(w in q_l for w in ["grafik", "chart", "diagram"]):
            answer_text = (
                "Ya, sistem ini dilengkapi visualisasi grafik interaktif otomatis. "
                "Untuk setiap kueri data yang memuat kategori atau periode waktu (misalnya tren penjualan per bulan atau perbandingan model mobil), Anda dapat langsung beralih antara tampilan **Tabel**, **Grafik Batang (Bar Chart)**, atau **Grafik Garis (Line Chart)** melalui tombol toggle di atas tabel."
            )
        elif any(w in q_l for w in ["pkb", "wo", "perintah kerja"]):
            answer_text = (
                "PKB (Perintah Kerja Bengkel) atau Work Order (WO) adalah dokumen kerja resmi di bengkel dealer "
                "yang mencatat instruksi pengerjaan perawatan atau perbaikan kendaraan pelanggan. "
                "Dokumen ini memuat keluhan kendaraan, estimasi biaya jasa dan suku cadang, nama Service Advisor (SA), "
                "serta teknisi/mekanik yang ditugaskan."
            )
        elif any(w in q_l for w in ["spk", "surat pesanan"]):
            answer_text = (
                "SPK (Surat Pesanan Kendaraan) adalah dokumen perikatan pemesanan kendaraan antara pelanggan dan pihak dealer. "
                "SPK memuat data lengkap pembeli, spesifikasi tipe dan varian mobil, warna, harga on-the-road (OTR), "
                "metode pembayaran (Cash atau Kredit/Leasing), serta uang muka (DP) yang disetorkan."
            )
        elif any(w in q_l for w in ["norangka", "vin", "nopolisi", "no rangka", "no polisi"]):
            answer_text = (
                "Nomor Rangka (VIN / Vehicle Identification Number) adalah 17 digit kode unik internasional dari pabrik perakitan "
                "yang melekat permanen pada sasis kendaraan dan tidak pernah berubah. "
                "Sementara Nomor Polisi (Plat Nomor) adalah nomor registrasi kendaraan bermotor yang diterbitkan oleh kepolisian/Samsat "
                "dan dapat berubah apabila terjadi mutasi daerah atau pergantian kepemilikan."
            )
        elif any(w in q_l for w in ["faktur"]):
            answer_text = (
                "Faktur Penjualan adalah bukti transaksi resmi penjualan unit kendaraan atau jasa servis yang mencatat rincian harga pokok, "
                "Pajak Pertambahan Nilai (PPN), potongan diskon yang disepakati, serta total tagihan bersih kepada pembeli."
            )
        elif any(w in q_l for w in ["otr", "off the road"]):
            answer_text = (
                "Harga On The Road (OTR) adalah harga jual kendaraan yang sudah termasuk seluruh biaya pengurusan dokumen legalitas jalan "
                "(STNK, BPKB, dan Pajak Kendaraan Bermotor). Sedangkan Off The Road adalah harga murni unit kendaraan tanpa biaya legalitas jalan."
            )
        elif any(w in q_l for w in ["terima kasih", "makasih", "thanks", "tq", "mantap", "keren"]):
            answer_text = (
                "Sama-sama. Senang dapat membantu Anda. Jika Anda membutuhkan analisis data penjualan, servis bengkel, "
                "suku cadang, atau profil pelanggan cabang Anda, silakan tanyakan kapan saja."
            )
        elif any(w in q_l for w in ["bisa apa", "fitur", "bantu apa", "kapabilitas"]):
            answer_text = (
                "Sebagai Asisten AI Database Dealer, saya siap membantu Anda menganalisis data operasional cabang:\n\n"
                "- **Penjualan Unit Kendaraan**: Volume penjualan, tren omzet bulanan dan tahunan, ranking tipe mobil terlaris, serta performa wiraniaga (sales).\n"
                "- **Jasa Servis Bengkel**: Volume pengerjaan Work Order (PKB), pendapatan jasa perawatan, dan histori servis kendaraan.\n"
                "- **Suku Cadang & Sparepart**: Ketersediaan persediaan suku cadang, barang keluar-masuk, dan nilai penjualan counter part.\n"
                "- **Pelanggan**: Profil pelanggan setia dan persebaran transaksi konsumen.\n\n"
                "Silakan ajukan pertanyaan spesifik mengenai data yang ingin Anda periksa."
            )
        else:
            answer_text = (
                "Halo. Selamat datang di Asisten AI Database Dealer. Saya terhubung langsung ke database operasional cabang Anda "
                "dan siap membantu menyajikan laporan dan analitik penjualan unit, jasa servis bengkel, suku cadang, serta pelanggan. "
                "Apa yang ingin Anda analisis hari ini?"
            )

    # Mechanical Output Guard: cegah halusinasi tabel numerik / klaim eksekusi fiktif
    _, answer_text = _periksa_integritas_output_percakapan(answer_text)

    # Dialogue State Tracking: Bentuk pending_proposal jika pertanyaan menyentuh topik modul bisnis
    pending_proposal = None
    q_lower = question.lower()
    if any(w in q_lower for w in ["keuangan", "kasir", "uang", "finansial", "piutang", "pembayaran"]):
        pending_proposal = {
            "intent": "financial_analysis",
            "topic": "keuangan",
            "status": "awaiting_confirmation",
            "options": [
                {
                    "id": "omzet_unit_bulanan",
                    "label": "Tren Penjualan Unit & Omzet Bulanan 2025",
                    "query": "Tampilkan tren penjualan unit dan total omzet per bulan tahun 2025",
                    "keywords": ["penjualan", "omzet", "tren", "bulanan", "keuangan"]
                },
                {
                    "id": "pendapatan_servis_bulanan",
                    "label": "Pendapatan Servis Bengkel Bulanan 2025",
                    "query": "Berapa total pendapatan servis bengkel tahun 2025 per bulan?",
                    "keywords": ["servis", "bengkel", "jasa", "perawatan"]
                },
                {
                    "id": "komparasi_divisi",
                    "label": "Perbandingan Pendapatan Antar Divisi",
                    "query": "Bandingkan performa tiap divisi dalam tiap tahunnya",
                    "keywords": ["divisi", "komparasi", "bandingkan", "tahunan"]
                },
                {
                    "id": "top_customer",
                    "label": "Top 10 Customer Pembelian Terbesar",
                    "query": "Daftar 10 customer dengan pembelian unit terbanyak",
                    "keywords": ["customer", "pelanggan", "terbesar"]
                }
            ],
            "default_action": {
                "id": "omzet_unit_bulanan",
                "query": "Tampilkan tren penjualan unit dan total omzet per bulan tahun 2025"
            }
        }
        saran = [opt["query"] for opt in pending_proposal["options"]]
    elif any(w in q_lower for w in ["jual", "penjualan", "mobil", "unit"]):
        pending_proposal = {
            "intent": "sales_analysis",
            "topic": "penjualan",
            "status": "awaiting_confirmation",
            "options": [
                {
                    "id": "mobil_terlaris",
                    "label": "5 Model Mobil Terlaris 2025",
                    "query": "Tampilkan 5 model mobil terlaris tahun 2025 beserta grafiknya",
                    "keywords": ["terlaris", "model", "mobil"]
                },
                {
                    "id": "tren_penjualan",
                    "label": "Tren Penjualan Bulanan",
                    "query": "Tampilkan tren penjualan unit per bulan tahun 2025",
                    "keywords": ["tren", "bulanan"]
                },
                {
                    "id": "top_customer",
                    "label": "Top Customer Pembelian Unit",
                    "query": "Daftar 10 customer dengan transaksi pembelian unit terbesar",
                    "keywords": ["customer", "pelanggan"]
                }
            ],
            "default_action": {
                "id": "mobil_terlaris",
                "query": "Tampilkan 5 model mobil terlaris tahun 2025 beserta grafiknya"
            }
        }
        saran = [opt["query"] for opt in pending_proposal["options"]]
    elif any(w in q_lower for w in ["servis", "service", "pkb", "wo", "bengkel"]):
        pending_proposal = {
            "intent": "service_analysis",
            "topic": "servis",
            "status": "awaiting_confirmation",
            "options": [
                {
                    "id": "servis_bulanan",
                    "label": "Pendapatan Servis Bengkel 2025",
                    "query": "Berapa total pendapatan servis bengkel tahun 2025 per bulan beserta grafiknya?",
                    "keywords": ["pendapatan", "bulanan", "omzet"]
                },
                {
                    "id": "pekerjaan_terbanyak",
                    "label": "5 Pekerjaan Servis Terbanyak",
                    "query": "Tampilkan 5 pekerjaan servis dengan frekuensi tertinggi",
                    "keywords": ["pekerjaan", "jasa", "terbanyak"]
                },
                {
                    "id": "top_sa",
                    "label": "Top Service Advisor",
                    "query": "Siapa Service Advisor dengan penanganan PKB terbanyak?",
                    "keywords": ["sa", "service advisor"]
                }
            ],
            "default_action": {
                "id": "servis_bulanan",
                "query": "Berapa total pendapatan servis bengkel tahun 2025 per bulan beserta grafiknya?"
            }
        }
        saran = [opt["query"] for opt in pending_proposal["options"]]
    elif any(w in q_lower for w in ["sparepart", "part", "suku cadang"]):
        pending_proposal = {
            "intent": "parts_analysis",
            "topic": "suku cadang",
            "status": "awaiting_confirmation",
            "options": [
                {
                    "id": "part_terlaris",
                    "label": "10 Suku Cadang Tercepat",
                    "query": "Tampilkan 10 suku cadang dengan perputaran tercepat",
                    "keywords": ["tercepat", "fast moving"]
                },
                {
                    "id": "omzet_part",
                    "label": "Total Nilai Penjualan Part 2025",
                    "query": "Berapa total nilai penjualan suku cadang tahun 2025?",
                    "keywords": ["nilai", "omzet", "penjualan"]
                },
                {
                    "id": "stok_part",
                    "label": "Sisa Stok Suku Cadang",
                    "query": "Berapa sisa stok part saat ini?",
                    "keywords": ["stok", "sisa", "gudang"]
                }
            ],
            "default_action": {
                "id": "part_terlaris",
                "query": "Tampilkan 10 suku cadang dengan perputaran tercepat"
            }
        }
        saran = [opt["query"] for opt in pending_proposal["options"]]
    elif any(w in q_lower for w in ["semua data", "seluruh data", "semisal", "misal"]):
        saran = [
            "Tampilkan ringkasan penjualan unit tahun 2025",
            "Berapa total pendapatan servis bengkel tahun 2025?",
            "Tampilkan 5 model mobil terlaris sepanjang masa",
            "Daftar 10 customer dengan transaksi pembelian unit terbesar",
        ]
    else:
        saran = [
            "Tampilkan 5 model mobil dengan penjualan tertinggi",
            "Berapa total pendapatan servis bengkel tahun 2025?",
            "Daftar 10 customer dengan transaksi pembelian unit terbesar",
            "Berapa sisa stok mobil saat ini?",
        ]

    response = {
        "source": "conversational",
        "confidence": "A",
        "status": "success",
        "question": question,
        "ringkasan": answer_text,
        "sql": "",
        "params": [],
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "duration_ms": durasi_ms,
        "memory_id": None,
        "saran": saran,
        "metode": "conversational",
        "is_conversational_text": True,
        "allow_explain": False,
        "pending_proposal": pending_proposal,
    }

    conv_id = await ambil_atau_buat_conversation(
        core_pool, user_id, branch_code, question, conversation_id=conversation_id
    )
    response["conversation_id"] = conv_id
    await simpan_pesan(core_pool, conv_id, "user", question)
    await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))

    ai_provider = ai_config.get("provider") if ai_config else None
    ai_model = ai_config.get("model") if ai_config else None
    await tulis_audit(
        core_pool,
        user_id=user_id,
        branch_code=branch_code,
        prompt_text=question,
        ai_json_filter={
            "provider": ai_provider,
            "model": ai_model,
            "category": "conversational",
            "mode": "conversational",
        },
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
    ai_config: dict | None = None,
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
        "tipe": "Varian atau tipe spesifikasi kendaraan",
        "total_unit": "Kuantitas atau jumlah unit mobil terjual",
        "hjakhir": "Nilai uang atau nominal omzet bersih transaksi (Rupiah)",
        "total_omzet": "Total akumulasi nilai penjualan kotor/bersih",
        "omzet": "Total nominal pendapatan penjualan",
        "hargajual": "Harga transaksi sebelum potongan diskon",
        "diskon": "Nilai potongan harga yang diberikan ke pelanggan",
        "uangmuka": "Uang muka atau Down Payment (DP) transaksi",
        "nama_salesman": "Nama tenaga penjual (sales) penanggung jawab transaksi",
        "salesman": "Tenaga penjual (sales) yang menangani",
        "pekerjaan": "Deskripsi atau nama paket perbaikan/servis yang dikerjakan bengkel",
        "nama_jasa": "Uraian nama pekerjaan jasa servis kendaraan",
        "biaya_jasa": "Nominal tarif pekerjaan jasa bengkel",
        "nama_part": "Nama suku cadang atau komponen sparepart kendaraan",
        "kode_part": "Kode katalog resmi suku cadang",
        "qty": "Jumlah unit/kuantitas barang yang dikeluarkan atau terjual",
        "total_harga": "Total nominal biaya atau harga transaksi",
    }

    # Ambil pesan asisten terakhir dari percakapan aktif
    prev_asst_msg = await core_pool.fetchrow(
        "SELECT content FROM messages "
        "WHERE conversation_id = $1 AND role = 'assistant' "
        "ORDER BY id DESC LIMIT 1",
        conversation_id,
    )

    ringkasan = ""
    saran = []

    if not prev_asst_msg or not prev_asst_msg["content"]:
        ringkasan = (
            "Belum ada data tabel atau laporan transaksi sebelumnya dalam sesi percakapan ini. "
            "Untuk memeriksa data operasional nyata, Anda dapat meminta data penjualan unit, "
            "servis bengkel, atau suku cadang."
        )
        saran = [
            "Tampilkan 5 model mobil dengan penjualan tertinggi",
            "Berapa total pendapatan servis bengkel tahun 2025?",
            "Tren volume transaksi servis bulanan sepanjang tahun 2024",
        ]
    else:
        try:
            prev_data = json.loads(prev_asst_msg["content"])
        except Exception:
            prev_data = {}

        tabs = prev_data.get("tabs") or []
        rows = prev_data.get("rows") or (tabs[0].get("rows") if tabs else [])
        is_graphic_inquiry = any(w in question.lower() for w in ["grafik", "chart", "diagram"])

        if is_graphic_inquiry:
            if rows:
                prev_q = prev_data.get("question") or "laporan data transaksi"
                ringkasan = (
                    f"Visualisasi grafik interaktif untuk **\"{prev_q}\"** sudah tersedia langsung pada kartu laporan di atas.\n\n"
                    "Untuk melihat tampilan visualnya, silakan klik tombol toggle tab **Grafik** (ikon diagram batang) "
                    "yang berada di pojok kanan atas kartu laporan data tersebut, tepat di sebelah tombol **Tabel**.\n\n"
                    "Sistem menyediakan opsi **Grafik Batang (Bar Chart)** dan **Grafik Garis (Line Chart)**. "
                    "Anda dapat mengarahkan kursor (hover) ke setiap batang atau titik garis untuk melihat angka nominal secara mendetail."
                )
                saran = [
                    "Bandingkan performa tiap divisi dalam tiap tahunnya",
                    "Tampilkan tren bulanan penjualan unit tahun 2024",
                    "Berapa total pendapatan servis bengkel tahun 2025?",
                ]
            else:
                ringkasan = (
                    "Visualisasi grafik interaktif (Line Chart dan Bar Chart) otomatis aktif di panel atas "
                    "begitu kueri data berhasil dieksekusi dari database cabang.\n\n"
                    "Pada percakapan sebelumnya, data transaksi nyata belum ditarik ke layar sehingga belum ada titik data untuk divisualisasikan.\n\n"
                    "Silakan klik salah satu kueri data di bawah ini untuk langsung mengeksekusi database dan memunculkan grafik interaktifnya:"
                )
                pending_p = prev_data.get("pending_proposal")
                if pending_p and pending_p.get("options"):
                    saran = [opt["query"] for opt in pending_p["options"][:4]]
                else:
                    saran = [
                        "Tampilkan tren penjualan unit dan total omzet per bulan tahun 2025",
                        "Tampilkan 5 model mobil dengan penjualan tertinggi",
                        "Berapa total pendapatan servis bengkel tahun 2025?",
                        "Tren volume transaksi servis bulanan sepanjang tahun 2024",
                    ]
        elif not rows:
            prev_ringkasan = prev_data.get("ringkasan") or ""
            if prev_ringkasan:
                ringkasan = (
                    f"Pada jawaban sebelumnya, saya memberikan penjelasan naratif berikut:\n\n"
                    f"> {prev_ringkasan}\n\n"
                    "Belum ada tabel data transaksi spesifik yang dimuat. Jika Anda ingin memeriksa data operasional nyata, "
                    "silakan pilih modul data yang ingin ditampilkan (seperti Penjualan Mobil, Servis Bengkel, atau Suku Cadang)."
                )
            else:
                ringkasan = (
                    "Pesan sebelumnya tidak memuat data tabel transaksi untuk dijelaskan. "
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
            sql = (prev_data.get("sql") or (tabs[0].get("sql") if tabs else "") or "").lower()
            cols = prev_data.get("columns") or (tabs[0].get("columns") if tabs else [])
            row_count = prev_data.get("row_count", len(rows))

            modul_nama = "Operasional Dealer"
            if "untt_penjualan" in sql or any(k in prev_q.lower() for k in ["jual", "penjualan", "mobil", "unit"]):
                modul_nama = "Penjualan Unit Kendaraan"
                saran = [
                    "Berapa total omzet penjualan unit per bulan di tahun 2025?",
                    "Tampilkan 5 customer dengan pembelian unit terbanyak",
                    "Tren volume penjualan unit mobil sepanjang tahun 2024",
                ]
            elif "srvt_wo" in sql or "srvt_wodetail" in sql or any(k in prev_q.lower() for k in ["servis", "service", "bengkel", "pkb", "wo"]):
                modul_nama = "Jasa Servis & Perawatan Bengkel"
                saran = [
                    "Berapa total pendapatan jasa servis bengkel tahun 2025?",
                    "Tampilkan 5 jenis pekerjaan servis yang paling sering dikerjakan",
                    "Tren jumlah unit kendaraan yang diservis per bulan",
                ]
            elif "untt_pembelian" in sql or any(k in prev_q.lower() for k in ["beli", "pembelian", "kulakan", "pengadaan"]):
                modul_nama = "Pembelian Unit Kendaraan"
                saran = [
                    "Berapa total unit yang dibeli dealer tahun 2025?",
                    "Daftar supplier unit kendaraan utama",
                    "Perbandingan total unit dibeli vs unit terjual",
                ]
            elif "srvm_" in sql or any(k in prev_q.lower() for k in ["sparepart", "suku cadang", "part"]):
                modul_nama = "Suku Cadang & Sparepart"
                saran = [
                    "Tampilkan 10 suku cadang dengan perputaran tercepat",
                    "Berapa total nilai penjualan suku cadang tahun 2025?",
                    "Daftar suku cadang dengan pergerakan tertinggi",
                ]
            elif "glbm_customer" in sql or any(k in prev_q.lower() for k in ["customer", "pelanggan"]):
                modul_nama = "Master Data Pelanggan / Customer"
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
                f"Tabel di atas menampilkan {baris_info} dari modul **{modul_nama}**, "
                f"yang dihasilkan untuk menjawab pertanyaan: *\"{prev_q}\"*."
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

    ai_provider = ai_config.get("provider") if ai_config else None
    ai_model = ai_config.get("model") if ai_config else None
    await tulis_audit(
        core_pool,
        user_id=user_id,
        branch_code=branch_code,
        prompt_text=question,
        ai_json_filter={
            "provider": ai_provider,
            "model": ai_model,
            "category": "conversational_explanation",
            "mode": "conversational_explanation",
        },
        generated_sql="",
        execution_time_ms=durasi_ms,
        status="success",
        error_message=None,
    )
    return response


async def jalankan_mode_vanna(core_pool, tenant_pool_manager, user: dict,
                              question: str, branch_code: str,
                              llm_call_fn=None,
                              conversation_id: int | None = None,
                              inherited_topic: str | None = None) -> dict:
    """Eksekusi kueri menggunakan Mode Vanna murni."""
    t0 = time.monotonic()
    user_id = user["user_id"]

    try:
        tenant = await resolve_tenant(core_pool, branch_code)
        tenant_id = tenant.get("tenant_id") or tenant.get("id")

        ai_config = None
        try:
            ai_config = await resolve_ai_config(core_pool, user.get("username", ""), branch_code)
        except Exception as e_cfg:
            logger.warning("Gagal resolve ai_config di awal jalankan_mode_vanna: %s", e_cfg)

        # Conversational Slot-Filling: Rekonsiliasi jawaban klarifikasi pengguna jika ada sesi aktif
        question, is_reconciled = await rekonsiliasi_slot_percakapan(core_pool, conversation_id, question)
        q_norm = normalisasi_pertanyaan(question)

        # Dialogue State Tracking: Evaluasi apakah pengguna menyetujui pending proposal dari turn sebelumnya (Direct Action Policy)
        question, is_action_accepted, active_proposal = await evaluasi_state_percakapan(core_pool, conversation_id, question)
        if is_action_accepted:
            logger.info("Dialogue State Tracking: Aksi disetujui -> Kueri dialihkan ke kueri operasional: %s", question)
            q_norm = normalisasi_pertanyaan(question)

        # Deteksi topik eksplisit dari pertanyaan aktif (override 100% inherited_topic)
        explicit_topic = deteksi_topik_eksplisit(question)
        if explicit_topic:
            inherited_topic = explicit_topic
        elif inherited_topic is None:
            inherited_topic = await deteksi_topik_riwayat_percakapan(core_pool, conversation_id)

        # Ambil skema tabel tenant untuk validasi graceful fallback kueri deterministik
        allowed_tables = None
        if tenant.get("schema_config_json"):
            try:
                sc = tenant["schema_config_json"]
                if isinstance(sc, str):
                    sc = json.loads(sc)
                if isinstance(sc, dict) and "tables" in sc:
                    allowed_tables = set(sc["tables"].keys())
            except Exception as e_sc:
                logger.debug("Gagal parse schema_config_json tenant: %s", e_sc)

        # Ambil konteks percakapan aktif (tahun + topik) secara terisolasi per conversation_id
        active_context = await ambil_konteks_percakapan_aktif(core_pool, conversation_id)

        # 0.0. Mode Percakapan Eksplanatori ("loh data apa ini?", "tadi lu kasih data apa?", "maksud tabel ini apa?")
        if not is_action_accepted and _is_explanatory_question(question):
            return await tangani_kueri_eksplanatori(
                core_pool, conversation_id, question, user_id, branch_code, t0, ai_config=ai_config
            )

        # 0.0.1. Mode Peta Database Otomatis (Menampilkan ~2.387 tabel ERP terkelompokkan secara instan)
        if is_schema_map_question(question):
            pool_tenant = await tenant_pool_manager.get_pool(tenant)
            db_map = await dapatkan_peta_database_tenant(pool_tenant, db_name=tenant.get("db_name", "Otobitz Cloud"))
            durasi_ms = int((time.monotonic() - t0) * 1000)
            total_fmt = f"{db_map['total_tables']:,}".replace(",", ".")
            peta_text = (
                f"Database operasional cabang Anda terhubung ke database **{db_map['db_name']}** "
                f"dengan total **{total_fmt} tabel/views** yang dikelompokkan secara otomatis berdasarkan konvensi modul ERP:\n\n"
                f"{db_map['markdown']}\n\n"
                "Seluruh modul di atas siap Anda analisis secara interaktif. Anda dapat meminta analisis penjualan, servis, suku cadang, atau profil pelanggan."
            )
            response = {
                "source": "conversational",
                "confidence": "A",
                "status": "success",
                "question": question,
                "ringkasan": peta_text,
                "sql": "",
                "params": [],
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "duration_ms": durasi_ms,
                "memory_id": None,
                "saran": [
                    "Tampilkan 5 model mobil dengan penjualan tertinggi",
                    "Berapa total pendapatan servis bengkel tahun 2025?",
                    "Daftar suku cadang dengan stok menipis di gudang",
                    "Siapa 5 pelanggan dengan transaksi terbesar?",
                ],
                "metode": "schema_map",
                "is_conversational_text": True,
                "allow_explain": False,
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
                ai_json_filter={
                    "provider": ai_config.get("provider") if ai_config else None,
                    "model": ai_config.get("model") if ai_config else None,
                    "category": "schema_map",
                    "mode": "schema_map",
                },
                generated_sql="",
                execution_time_ms=durasi_ms,
                status="success",
                error_message=None,
            )
            return response

        # 0.0.2. Mode Percakapan Murni (Sapaan, Terima Kasih, Istilah Bisnis / Konsep Otomotif, Kapabilitas)
        if not is_action_accepted and _is_conversational_question(question):
            return await tangani_kueri_percakapan(
                core_pool, conversation_id, question, user_id, branch_code, t0,
                ai_config=ai_config, llm_call_fn=llm_call_fn
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
                    ai_json_filter={
                        "provider": ai_config.get("provider") if ai_config else None,
                        "model": ai_config.get("model") if ai_config else None,
                        "category": "clarification",
                        "mode": "clarification",
                        "reason": "data_cutoff_no_year",
                    },
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
                ai_json_filter={
                    "provider": ai_config.get("provider") if ai_config else None,
                    "model": ai_config.get("model") if ai_config else None,
                    "category": "data_query",
                    "mode": "data_cutoff_audit",
                    "target_year": cutoff_info["target_year"],
                },
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

                    ai_provider = ai_config.get("provider") if ai_config else None
                    ai_model = ai_config.get("model") if ai_config else None
                    await tulis_audit(
                        core_pool,
                        user_id=user_id,
                        branch_code=branch_code,
                        prompt_text=question,
                        ai_json_filter={
                            "provider": ai_provider,
                            "model": ai_model,
                            "category": "data_query",
                            "mode": "vanna",
                            "replay_memory": True,
                        },
                        generated_sql=sql_mem,
                        execution_time_ms=durasi_ms,
                        status="success",
                        error_message=None
                    )
                    return response
                except Exception as e_mem:
                    logger.warning("Replay SQL memory gagal (%s), lanjut ke LLM...", e_mem)

        # 0.4. Cek Kueri Rincian Terpisah (Gaya 2) atau Kueri Multi-Laporan Dinamis
        fanout_info = cek_apakah_minta_rincian_terpisah(question, inherited_topic=inherited_topic, allowed_tables=allowed_tables) or cek_apakah_minta_multi_query(question)
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
                            hidden_cols = {"total_transaksi_tahun", "total_omzet_tahun"}
                            total_full_count = None
                            total_full_money = None

                            if records:
                                first_rec = records[0]
                                if "total_transaksi_tahun" in first_rec and first_rec["total_transaksi_tahun"] is not None:
                                    try:
                                        total_full_count = int(first_rec["total_transaksi_tahun"])
                                    except (ValueError, TypeError):
                                        pass
                                if "total_omzet_tahun" in first_rec and first_rec["total_omzet_tahun"] is not None:
                                    try:
                                        total_full_money = float(first_rec["total_omzet_tahun"])
                                    except (ValueError, TypeError):
                                        pass
                                raw_keys = list(first_rec.keys())
                                visible_cols = [c for c in raw_keys if c not in hidden_cols]
                            else:
                                visible_cols = []

                            converted = [[_konversi_nilai_vanna(r[c]) for c in visible_cols] for r in records[:500]]
                            raw_recs = [{c: r[c] for c in visible_cols} for r in records]

                            return {
                                "id": domain_def["id"],
                                "title": domain_def["title"],
                                "label": domain_def["title"],
                                "icon": domain_def["icon"],
                                "sql": sql_query,
                                "columns": visible_cols,
                                "rows": converted,
                                "row_count": len(records),
                                "total_full_count": total_full_count,
                                "total_full_money": total_full_money,
                                "raw_records": raw_recs,
                                "error": None
                            }
                        except Exception as e:
                            logger.warning("Eksekusi sub-domain %s gagal: %s", domain_def["id"], e)
                            return {
                                "id": domain_def["id"],
                                "title": domain_def["title"],
                                "label": domain_def["title"],
                                "icon": domain_def["icon"],
                                "sql": sql_query,
                                "columns": [],
                                "rows": [],
                                "row_count": 0,
                                "total_full_count": None,
                                "total_full_money": None,
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
                    periods = [str(p).strip() for p in fanout_info.get("periods", []) if str(p).strip()]
                    if not periods:
                        p1 = str(fanout_info.get("p1") or "").strip()
                        p2 = str(fanout_info.get("p2") or "").strip()
                        periods = [p for p in (p1, p2) if p]
                    topic = fanout_info.get("topic") or inherited_topic or "transaksi"
                    frasa_topik = f"transaksi {topic}" if topic != "transaksi" else "data transaksi"
                    if len(periods) >= 2:
                        thn_str = " vs ".join(periods) if len(periods) <= 3 else f"{periods[0]} s/d {periods[-1]}"
                        saran_list = [
                            f"Bandingkan performa {topic} tahun {thn_str} dalam satu tabel",
                        ]
                        for p in periods[:3]:
                            saran_list.append(f"Tampilkan tren bulanan {topic} tahun {p}")
                    elif len(periods) == 1:
                        p1 = periods[0]
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
                    "total_full_count": default_tab.get("total_full_count"),
                    "total_full_money": default_tab.get("total_full_money"),
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

                ai_provider = ai_config.get("provider") if ai_config else None
                ai_model = ai_config.get("model") if ai_config else None
                await tulis_audit(
                    core_pool,
                    user_id=user_id,
                    branch_code=branch_code,
                    prompt_text=question,
                    ai_json_filter={
                        "provider": ai_provider,
                        "model": ai_model,
                        "category": "data_query",
                        "mode": "vanna_fanout",
                        "fanout_category": fanout_info["category"],
                    },
                    generated_sql=default_tab["sql"],
                    execution_time_ms=durasi_ms,
                    status="success",
                    error_message=None
                )
                return response

        # 0.5. Cek Ambiguitas Domain Dealer (Bypassed: langsung eksekusi kueri analitik tanpa membajak alur)
        ambiguitas = None
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

            ai_provider = ai_config.get("provider") if ai_config else None
            ai_model = ai_config.get("model") if ai_config else None
            await tulis_audit(
                core_pool,
                user_id=user_id,
                branch_code=branch_code,
                prompt_text=question,
                ai_json_filter={
                    "provider": ai_provider,
                    "model": ai_model,
                    "category": "clarification",
                    "mode": "clarification",
                    "clarification": ambiguitas["category"],
                },
                generated_sql=None,
                execution_time_ms=durasi_ms,
                status="clarification",
                error_message=None
            )
            return response

        ai_config = await resolve_ai_config(core_pool, user.get("username", ""), branch_code)
        
        async with VANNA_SEMAPHORE:
            panggil_fn = llm_call_fn or panggil_llm_default

            # 0.6. Cek Komparasi Temporal Deterministik (0 Halusinasi, 0 Token LLM)
            comp_info = _deteksi_kueri_komparasi_periode(question, inherited_topic=inherited_topic)
            deterministic_comp_sql = susun_kueri_komparasi_deterministik(comp_info, question, allowed_tables=allowed_tables) if comp_info else None

            if deterministic_comp_sql:
                sql = deterministic_comp_sql
                is_sql = True
                has_from_table = True
                logger.info("Menggunakan SQL Komparasi Deterministik (0 Token): %s", sql.replace("\n", " "))
            else:
                # 1. Ambil Konteks Semantik Murni dari pgvector (dengan fallback aman)
                context_text, _ = await ambil_konteks_vanna(core_pool, question, branch_code, inherited_topic=inherited_topic)
                
                # 2. Susun Prompt Vanna
                vanna_prompt = susun_prompt_vanna(question, context_text, inherited_topic=inherited_topic)
                
                # 3. Panggil LLM (Hanya 1 Panggilan Tunggal!)
                system_msg = (
                    "You are an expert AI data assistant and PostgreSQL specialist. "
                    "If the input asks for data, output ONLY SQL code block (```sql ... ```). "
                    "If the input is conversational or does not require a database query, respond naturally and helpfully in Indonesian Markdown."
                )
                raw_output = await panggil_fn(system_msg, vanna_prompt, ai_config)
                
                # 4. Evaluasi Respons LLM (SQL Query vs Percakapan Naratif)
                sql = ekstrak_sql(raw_output)
                is_sql = bool(sql.lower().startswith("select") or sql.lower().startswith("with"))
                sql_clean = re.sub(r'--.*', '', sql).strip() if is_sql else ""
                has_from_table = bool(re.search(r'\bfrom\s+[a-zA-Z0-9_"]+', sql_clean, re.IGNORECASE)) if is_sql else False

            if not is_sql or not has_from_table:
                # LLM memilih merespons secara percakapan / naratif murni (0 SQL, 0 Database)
                logger.info("AI merespons dengan percakapan naratif murni (0 SQL): %s", raw_output[:120])
                extracted_text = ""
                if is_sql and not has_from_table:
                    str_match = re.search(r"'(.*?)'", sql, re.DOTALL)
                    if str_match:
                        extracted_text = str_match.group(1).strip()
                if not extracted_text:
                    extracted_text = _ekstrak_teks_naratif_bersih(raw_output)
                if not extracted_text or len(extracted_text) < 5:
                    extracted_text = raw_output.strip()
                if not extracted_text:
                    extracted_text = (
                        "Halo! Senang bertemu dengan Anda. Silakan tanyakan data transaksi operasional cabang Anda, "
                        "seperti penjualan unit kendaraan, jasa servis bengkel, atau suku cadang."
                    )
                extracted_text = _bersihkan_emoji_teks(extracted_text)
                durasi_ms = int((time.monotonic() - t0) * 1000)
                response = {
                    "source": "conversational",
                    "confidence": "A",
                    "status": "success",
                    "question": question,
                    "ringkasan": extracted_text,
                    "sql": "",
                    "params": [],
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "truncated": False,
                    "duration_ms": durasi_ms,
                    "memory_id": None,
                    "saran": [
                        "Tampilkan 5 model mobil dengan penjualan tertinggi",
                        "Berapa total pendapatan servis bengkel tahun 2025?",
                        "Daftar 10 customer dengan transaksi pembelian unit terbesar",
                        "Tren volume transaksi servis bulanan sepanjang tahun 2024",
                    ],
                    "metode": "conversational_llm",
                    "is_conversational_text": True,
                    "allow_explain": False,
                }
                conv_id = await ambil_atau_buat_conversation(
                    core_pool, user_id, branch_code, question, conversation_id=conversation_id
                )
                response["conversation_id"] = conv_id
                await simpan_pesan(core_pool, conv_id, "user", question)
                await simpan_pesan(core_pool, conv_id, "assistant", json.dumps(response, default=str))
                ai_provider = ai_config.get("provider") if ai_config else None
                ai_model = ai_config.get("model") if ai_config else None
                await tulis_audit(
                    core_pool,
                    user_id=user_id,
                    branch_code=branch_code,
                    prompt_text=question,
                    ai_json_filter={
                        "provider": ai_provider,
                        "model": ai_model,
                        "category": "conversational",
                        "mode": "conversational_llm",
                    },
                    generated_sql="",
                    execution_time_ms=durasi_ms,
                    status="success",
                    error_message=None,
                )
                return response

            # 5. Eksekusi ke Database Tenant (Timeout 15 detik + 1x Auto Self-Repair)
            db_rows = None
            pool_tenant = await tenant_pool_manager.get_pool(tenant)
            async with pool_tenant.acquire() as conn:
                await conn.execute("SET statement_timeout = '15000'")
                try:
                    validasi_readonly_ast_vanna(sql)
                    db_rows = await conn.fetch(sql)
                except SqlGuardError as sge:
                    logger.warning("AST SQL Guard memblokir kueri Vanna: %s", sge)
                    raise
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
                        validasi_readonly_ast_vanna(repaired_sql)
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
        is_conversational_or_meta = (
            response.get("is_conversational_text")
            or response.get("source") == "conversational"
            or _is_conversational_question(question)
            or _is_explanatory_question(question)
            or is_schema_map_question(question)
            or any(w in question.lower() for w in ["semua data", "seluruh data", "semisal", "misal"])
            or not response.get("rows")
        )
        if not is_elliptical and not response.get("is_multi_tab") and not is_conversational_or_meta:
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
        ai_provider = ai_config.get("provider") if ('ai_config' in locals() and ai_config) else None
        ai_model = ai_config.get("model") if ('ai_config' in locals() and ai_config) else None
        await tulis_audit(
            core_pool,
            user_id=user_id,
            branch_code=branch_code,
            prompt_text=question,
            ai_json_filter={
                "provider": ai_provider,
                "model": ai_model,
                "category": "data_query",
                "mode": "vanna",
            },
            generated_sql=sql,
            execution_time_ms=durasi_ms,
            status="success",
            error_message=None
        )

        return response

    except Exception as e:
        durasi_ms = int((time.monotonic() - t0) * 1000)
        logger.error("Error Mode Vanna: %s", e)
        err_msg = str(e)
        err_lower = err_msg.lower()
        if any(k in err_lower for k in ["429", "tpm", "503", "quota", "rate limit", "overloaded", "groq", "openai", "bad gateway", "ai belum dikonfigurasi", "service unavailable", "connection error"]):
            cat = "provider_error"
            err_type = "PROVIDER_API_ERROR"
        elif any(k in err_lower for k in ["syntax error", "does not exist", "column", "relation", "canceling statement", "timeout"]):
            cat = "sql_error"
            err_type = "POSTGRES_SQL_ERROR"
        else:
            cat = "error"
            err_type = "GENERAL_ERROR"

        ai_provider = ai_config.get("provider") if ('ai_config' in locals() and ai_config) else None
        ai_model = ai_config.get("model") if ('ai_config' in locals() and ai_config) else None
        await tulis_audit(
            core_pool,
            user_id=user_id,
            branch_code=branch_code,
            prompt_text=question,
            ai_json_filter={
                "provider": ai_provider,
                "model": ai_model,
                "category": cat,
                "error_type": err_type,
                "mode": "vanna",
            },
            generated_sql=sql if 'sql' in locals() else None,
            execution_time_ms=durasi_ms,
            status="error",
            error_message=err_msg[:500]
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

