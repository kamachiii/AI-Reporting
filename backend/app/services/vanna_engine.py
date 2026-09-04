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

logger = logging.getLogger(__name__)

# Concurrency Semaphore untuk membatasi beban query AI serentak (maksimal 5 serentak)
VANNA_SEMAPHORE = asyncio.Semaphore(5)

STOPWORDS = {
    'dan', 'di', 'ke', 'dari', 'pada', 'untuk', 'yang', 'ini', 'itu',
    'adalah', 'atau', 'vs', 'tahun', 'data', 'semua', 'tampilkan',
    'berikan', 'tolong', 'ada', 'berapa', 'banyak', 'cari', 'lihat',
    'bagaimana', 'apa', 'saja', 'daftar', 'list', 'mohon'
}


async def ambil_konteks_vanna(core_pool, question: str, branch_code: str = "GLOBAL") -> tuple[str, list[str]]:
    """Cari tabel dan DDL relevan menggunakan pgvector semantic search (fallback ke ILIKE jika error)."""
    try:
        return await cari_konteks_pgvector(core_pool, branch_code, question, limit=8)
    except Exception as e:
        logger.warning("Pencarian pgvector gagal (%s), fallback ke pencarian teks ILIKE...", e)

    raw_words = re.findall(r'[a-zA-Z0-9_]+', question.lower())
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

    return "\n\n".join(contexts), tables_found


def susun_prompt_vanna(question: str, context: str) -> str:
    """Susun prompt persis dengan template resmi Vanna AI."""
    return f"""You are a Postgres expert. Please help to generate a SQL query to answer the question. Your response should ONLY be based on the given context and follow the response guidelines and format instructions.

=== Context:
{context}

=== Question:
{question}

=== Response Guidelines:
1. If the provided context is sufficient, please generate a valid SQL query without any explanations.
2. Ensure the query runs cleanly on PostgreSQL.
3. Return ONLY the SQL query enclosed in ```sql ... ``` code block.
"""


def ekstrak_sql(llm_output: str) -> str:
    """Ekstrak SQL dari response LLM (markdown code block, JSON, atau plain text)."""
    text = llm_output.strip()

    # Cek jika LLM merespons format JSON murni atau dalam code block
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for k in ("sql", "query", "sql_query"):
                if k in data and isinstance(data[k], str):
                    text = data[k].strip()
                    break
    except Exception:
        m_json = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if m_json:
            try:
                data = json.loads(m_json.group(1))
                if isinstance(data, dict):
                    for k in ("sql", "query", "sql_query"):
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


def _format_ringkasan_otomatis(rows: list, columns: list) -> str:
    """Ringkasan naratif deterministik otomatis tanpa panggil LLM lagi (hemat 100% token)."""
    n = len(rows)
    if n == 0:
        return "Tidak ada data yang ditemukan untuk kueri ini."
    if n == 1:
        r = rows[0]
        items = []
        for k, v in list(r.items())[:4]:
            val_conv = _konversi_nilai_vanna(v)
            if any(u in k.lower() for u in ('jual', 'beli', 'total', 'harga', 'selisih', 'omzet')) and isinstance(val_conv, (int, float)):
                items.append(f"{k}: Rp {int(val_conv):,}".replace(",", "."))
            else:
                items.append(f"{k}: {val_conv}")
        return f"Ditemukan 1 baris hasil ({', '.join(items)})."
    
    # Deteksi apakah ini perbandingan tahunan / periode
    if "tahun" in columns:
        parts = []
        for r in rows[:4]:
            thn = r.get("tahun")
            col_qty = next((c for c in columns if any(k in c.lower() for k in ('transaksi', 'jumlah', 'unit', 'qty'))), None)
            col_uang = next((c for c in columns if any(k in c.lower() for k in ('harga', 'beli', 'jual', 'total', 'nilai', 'omzet')) and c != col_qty and c.lower() != 'tahun'), None)

            sub = []
            if col_qty and r.get(col_qty) is not None:
                q_val = r.get(col_qty)
                sub.append(f"{int(q_val):,} transaksi".replace(",", "."))
            if col_uang and r.get(col_uang) is not None:
                u_val = r.get(col_uang)
                sub.append(f"total Rp {int(u_val):,}".replace(",", "."))

            if thn is not None:
                if len(sub) > 1:
                    parts.append(f"Tahun {int(thn)}: {sub[0]} ({sub[1]})")
                elif sub:
                    parts.append(f"Tahun {int(thn)}: {sub[0]}")
                else:
                    parts.append(f"Tahun {int(thn)}")
        if parts:
            return f"Perbandingan per tahun: {', '.join(parts)}."

    return f"Berhasil menampilkan {n} baris data dari database."


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


async def jalankan_mode_vanna(core_pool, tenant_pool_manager, user: dict,
                              question: str, branch_code: str,
                              llm_call_fn=None) -> dict:
    """Eksekusi kueri menggunakan Mode Vanna murni."""
    t0 = time.monotonic()
    user_id = user["user_id"]

    try:
        tenant = await resolve_tenant(core_pool, branch_code)
        tenant_id = tenant.get("tenant_id") or tenant.get("id")
        q_norm = normalisasi_pertanyaan(question)

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
            try:
                pool_tenant = await tenant_pool_manager.get_pool(tenant)
                async with pool_tenant.acquire() as conn:
                    await conn.execute("SET statement_timeout = '30000'")
                    db_rows = await conn.fetch(sql_mem)

                durasi_ms = int((time.monotonic() - t0) * 1000)
                columns = [k for k in db_rows[0].keys()] if db_rows else []
                rows = [[_konversi_nilai_vanna(v) for v in r.values()] for r in db_rows[:500]]
                ringkasan = entri_memori["ringkasan"] or _format_ringkasan_otomatis(db_rows[:500], columns)

                try:
                    await tandai_memory_dipakai(core_pool, entri_memori["id"])
                except Exception:
                    pass

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
                    "ringkasan": ringkasan,
                    "saran": [],
                    "metode": "memory"
                }

                conv_id = await ambil_atau_buat_conversation(core_pool, user_id, branch_code, question)
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

        ai_config = await resolve_ai_config(core_pool, user.get("username", ""), branch_code)
        
        async with VANNA_SEMAPHORE:
            # 1. Ambil Konteks Semantik Murni dari pgvector (dengan fallback aman)
            context_text, _ = await ambil_konteks_vanna(core_pool, question, branch_code)
            
            # 2. Susun Prompt Vanna
            vanna_prompt = susun_prompt_vanna(question, context_text)
            
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
                    ringkasan = _format_ringkasan_otomatis(db_rows[:500], columns)
                    allow_explain = True
            else:
                # Mode Operasional: Ringkasan lokal cepat (0 token) + Tombol Jelaskan Lebih Dalam aktif
                ringkasan = _format_ringkasan_otomatis(db_rows[:500], columns)
                allow_explain = True

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
                "ringkasan": ringkasan,
                "saran": [],
                "metode": "vanna",
                "allow_explain": allow_explain
            }

        # Simpan ke SQL Memory agar pertanyaan yang sama berikutnya bernilai 0 token!
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
        conv_id = await ambil_atau_buat_conversation(core_pool, user_id, branch_code, question)
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
    narr_prompt = f"""Kueri Data:
Pertanyaan: {question}
SQL: {sql}
Hasil Data (sampel 5 baris pertama):
{json.dumps(rows[:5], default=str)}
Total Baris: {len(rows)}

Buatkan analisis naratif mendalam dan profesional dalam bahasa Indonesia mengenai data di atas untuk membantu pengambilan keputusan bisnis dealer."""
    
    return await panggil_fn(
        "You are a senior business data analyst. Provide thorough and insightful business narrative in Indonesian.",
        narr_prompt,
        ai_config
    )

