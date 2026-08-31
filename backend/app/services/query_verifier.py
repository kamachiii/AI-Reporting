"""F2.3' — Query Verifier: orkestrator gerbang #1–#5 (docs v2 §2).

Menggabungkan verifikasi offline (`sql_guard.verify_sql`, gerbang #1–#4)
dengan EXPLAIN pre-flight (gerbang #5) terhadap koneksi tenant.

Kontrak untuk pemanggil (F2.4 Executor + audit):
- `verify_query` TIDAK PERNAH mengeksekusi query user — hanya verifikasi.
- Verdict ok=True -> `detail["final_sql"]` SIAP DIEKSEKUSI (LIMIT 500 sudah
  dipaksa) dan `detail["explain"]` berisi estimasi planner. Pemanggil tetap
  WAJIB menjalankan gerbang #6 saat eksekusi: transaksi READ ONLY +
  statement_timeout 10 dtk + cap baris hasil + user DB read-only.
- Verdict ok=False -> `gate` + `reason` WAJIB dicatat ke audit log (keputusan
  verifier per gerbang, docs v2 §2). `reason` juga dipakai sebagai umpan
  balik self-repair Tier 2 (maks 2x, docs v2 §1).
- Gerbang #5 default-deny: EXPLAIN gagal (SQL sah secara parse tapi salah
  semantik terhadap DB, mis. tipe tak cocok / kolom tak cocok lebar) = TOLAK.

`tenant_conn_factory` adalah async callable tanpa argumen yang mengembalikan
koneksi tenant (asyncpg-compatible, minimal punya `fetch(...)`). Factory
di-inject agar mudah diuji; verifier TIDAK menutup/mengembalikan koneksi —
pemilik factory (pool) yang mengelola siklus hidupnya.
"""
import json
import logging

from app.services.sql_guard import verify_sql

logger = logging.getLogger(__name__)

# Budget gerbang #5 — estimasi planner PostgreSQL. Konstanta awal; dievaluasi
# ulang setelah eval Tier 2 jalan (F2.5), jangan diubah diam-diam.
EXPLAIN_MAX_COST = 100_000.0
EXPLAIN_MAX_ROWS = 500_000

_GATE_EXPLAIN = "explain"


def _tolak_explain(reason: str, **detail) -> dict:
    return {"ok": False, "gate": _GATE_EXPLAIN, "reason": reason, "detail": detail}


async def verify_query(sql: str, schema_config: dict, tenant_conn_factory,
                       kb_forbidden=None) -> dict:
    """Jalankan gerbang #1–#4 (offline) lalu #5 (EXPLAIN pre-flight).

    Args:
        sql: teks query dari user/planner.
        schema_config: bentuk `tenants.schema_config_json` (lihat
            schema_introspector.introspect_schema).
        tenant_conn_factory: async callable () -> koneksi tenant yang punya
            `fetch(sql)`. Di-inject supaya test tidak butuh DB nyata.
        kb_forbidden: `tabel_dilarang` dari knowledge base tenant (opsional).

    Returns:
        Verdict dict {ok, gate, reason, detail} — bentuk sama dengan
        `sql_guard.verify_sql`; ok=True menambah `detail["explain"]`
        = {"total_cost", "plan_rows"}.
    """
    # --- Gerbang #1–#4: offline, tidak menyentuh DB ---
    verdict = verify_sql(sql, schema_config, kb_forbidden=kb_forbidden)
    if not verdict["ok"]:
        return verdict
    final_sql = verdict["detail"]["final_sql"]

    # --- Gerbang #5: EXPLAIN pre-flight pada koneksi tenant ---
    conn = await tenant_conn_factory()
    try:
        rows = await conn.fetch(f"EXPLAIN (FORMAT JSON) {final_sql}")
    except Exception as e:  # fail-closed: kegagalan apa pun = tolak
        logger.info("verifier: EXPLAIN gagal (gate %s): %s", _GATE_EXPLAIN, e)
        return _tolak_explain(f"EXPLAIN gagal (SQL salah semantik terhadap DB): {e}",
                              final_sql=final_sql)

    try:
        cost, rows_est = _baca_explain(rows)
    except Exception as e:
        logger.info("verifier: output EXPLAIN tak terbaca: %s", e)
        return _tolak_explain(f"output EXPLAIN tidak terbaca: {e}",
                              final_sql=final_sql)

    if cost > EXPLAIN_MAX_COST:
        return _tolak_explain(
            f"estimasi cost {cost:.0f} melebihi budget {EXPLAIN_MAX_COST:.0f}",
            final_sql=final_sql, explain={"total_cost": cost, "plan_rows": rows_est})
    if rows_est > EXPLAIN_MAX_ROWS:
        return _tolak_explain(
            f"estimasi baris {rows_est} melebihi budget {EXPLAIN_MAX_ROWS}",
            final_sql=final_sql, explain={"total_cost": cost, "plan_rows": rows_est})

    logger.debug("verifier: lolos gerbang #5 (cost=%.0f rows=%d)", cost, rows_est)
    verdict["detail"]["explain"] = {"total_cost": cost, "plan_rows": rows_est}
    return verdict


def _baca_explain(rows) -> tuple[float, int]:
    """Baca (Total Cost, Plan Rows) dari hasil EXPLAIN (FORMAT JSON).

    asyncpg umumnya mengembalikan 1 baris berisi string JSON (bisa juga sudah
    berupa list/dict bila codec json aktif). Bentuk: [{"Plan": {...}}, ...].
    """
    payload = rows[0][0]
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    plan = payload[0]["Plan"]
    return float(plan["Total Cost"]), int(plan["Plan Rows"])
