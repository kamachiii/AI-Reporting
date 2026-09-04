"""Few-shot provider untuk prompt LLM planner & tier2 generator (F3).

Mengambil contoh pertanyaan→plan/SQL yang sudah terbukti benar dari dua
sumber:
1. sql_memory (approved, per-tenant) — contoh paling spesifik & terpercaya
2. global_knowledge_base (kind='example') — contoh umum lintas-tenant

Memory examples didahulukan (lebih relevan per tenant), global KB mengisi
sisa slot hingga max_total tercapai.
"""
import json
import logging

import re

logger = logging.getLogger(__name__)

# Regex untuk mengekstrak nama tabel dari klausa FROM / JOIN pada SQL contoh
_TABLE_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


def _sql_relevan_dengan_skema(sql: str, schema_tables: set[str] | None) -> bool:
    """Cek apakah SQL contoh hanya menyentuh tabel yang ADA di skema tenant.

    Jika schema_tables None/kosong -> loloskan (tanpa filter).
    Jika SQL menyebut tabel asing (mis. 'untt_pembelian' saat skema tenant
    tidak memiliki tabel tsb) -> tolak agar tidak memicu halusinasi tabel.
    """
    if not schema_tables or not sql:
        return True
    tabel_di_sql = _TABLE_REF_RE.findall(sql)
    if not tabel_di_sql:
        return True
    skema_lower = {s.lower() for s in schema_tables}
    return all(t.lower() in skema_lower for t in tabel_di_sql)


async def ambil_fewshot_memory(core_pool, tenant_id: int,
                                limit: int = 3) -> list[dict]:
    """Ambil entri sql_memory approved paling sering dipakai.
    
    Strategi: top-N berdasarkan times_used DESC (entri paling terpercaya
    dan paling sering dipakai = paling relevan umum).
    
    Returns: [{'pertanyaan': str, 'plan_json': dict|None, 'sql': str, 'sumber': str}, ...]
    """
    try:
        rows = await core_pool.fetch(
            "SELECT pertanyaan_ternormalisasi, plan_json, sql, sumber "
            "FROM sql_memory "
            "WHERE tenant_id = $1 AND status = 'approved' "
            "ORDER BY times_used DESC, last_used DESC NULLS LAST "
            "LIMIT $2",
            tenant_id, limit
        )
        results = []
        for row in rows:
            plan = None
            if row["plan_json"]:
                if isinstance(row["plan_json"], str):
                    try:
                        plan = json.loads(row["plan_json"])
                    except json.JSONDecodeError:
                        plan = None
                else:
                    plan = row["plan_json"]
                    
            results.append({
                "pertanyaan": row["pertanyaan_ternormalisasi"],
                "plan_json": plan,
                "sql": row["sql"],
                "sumber": row["sumber"]
            })
        return results
    except Exception as e:
        logger.error(f"Gagal mengambil fewshot_memory: {e}")
        return []


async def ambil_fewshot_global(core_pool, limit: int = 2,
                              schema_tables: set[str] | None = None) -> list[dict]:
    """Ambil contoh question→SQL dari global KB yang relevan dengan skema tenant.
    
    Returns: [{'pertanyaan': str, 'sql': str}, ...]
    """
    try:
        # Ambil buffer lebih banyak bila perlu filter skema
        fetch_limit = limit * 4 if schema_tables else limit
        rows = await core_pool.fetch(
            "SELECT question, sql_example "
            "FROM global_knowledge_base "
            "WHERE kind = 'example' AND question IS NOT NULL AND sql_example IS NOT NULL "
            "ORDER BY updated_at DESC "
            "LIMIT $1",
            fetch_limit
        )
        filtered = []
        for row in rows:
            sql = row["sql_example"]
            if _sql_relevan_dengan_skema(sql, schema_tables):
                filtered.append({
                    "pertanyaan": row["question"],
                    "sql": sql
                })
                if len(filtered) >= limit:
                    break
        return filtered
    except Exception as e:
        logger.warning(f"Gagal mengambil fewshot_global (mungkin tabel belum ada): {e}")
        return []


async def ambil_fewshot(core_pool, tenant_id: int,
                        schema_tables: set[str] | None = None,
                        max_total: int = 5) -> list[dict]:
    """Gabung few-shot dari memory (prioritas) + global KB (disaring skema).
    
    Memory examples didahulukan (lebih spesifik per tenant),
    global KB mengisi sisa slot hanya jika relevan dengan skema tenant.
    
    Returns: list of dicts, each with at least 'pertanyaan' and either
             'plan_json' or 'sql' (or both).
    """
    memory_limit = min(max_total, 3)
    memory_examples = await ambil_fewshot_memory(core_pool, tenant_id, limit=memory_limit)
    
    remaining_slots = max_total - len(memory_examples)
    global_examples = []
    
    if remaining_slots > 0:
        global_examples = await ambil_fewshot_global(
            core_pool, limit=remaining_slots, schema_tables=schema_tables)
        
    return memory_examples + global_examples
