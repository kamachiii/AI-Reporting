"""SQL Guard (F2.3) — gerbang keamanan sebelum query dieksekusi ke tenant DB.

Kontrak (didefinisikan oleh tests/test_sql_guard.py, TDD):
    validate_readonly_query(sql: str, allowed_tables: set[str]) -> None

Raise ValueError pada setiap pelanggaran; return normal bila lolos.

Gerbang (sesuai docs/PERANCANGAN-PIPELINE-AI.md §4 gerbang #3):
1. Parse tunggal  — multi-statement ditolak (exp.Block / hasil parse > 1)
2. Read-only      — hanya exp.Select di level atas; DDL/DML (DROP, DELETE,
                    UPDATE, INSERT, TRUNCATE, ALTER, CREATE, ...) ditolak
3. Whitelist      — semua tabel yang direferensikan harus ada di allowed_tables;
                    information_schema/pg_catalog ditangkap di sini juga karena
                    tidak pernah ada di whitelist
4. Fungsi berbahaya — pg_sleep & kerabat DoS diblokir walau dibungkus ekspresi

Catatan sqlglot: parse dilakukan dengan read="postgres" karena tenant DB
adalah PostgreSQL. Unparsable input tetap ditolak (fail-closed).
"""
import logging

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

logger = logging.getLogger(__name__)

# Fungsi yang dipakai untuk DoS / manipulasi waktu eksekusi.
# pg_sleep & varianten; daftar kecil dan eksplisit (bukan blacklist luas).
_DANGEROUS_FUNCTIONS = {
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "pg_terminate_backend",
    "pg_cancel_backend",
}


class SqlGuardError(ValueError):
    """Pelanggaran kebijakan query read-only. Subclass ValueError agar
    penanganan lama (wrap ValueError -> HTTP 400) tetap bekerja."""


def _extract_table_names(tree: exp.Expression) -> set[str]:
    """Kumpulkan semua nama tabel yang direferensikan AST (tanpa alias)."""
    names: set[str] = set()
    for table in tree.find_all(exp.Table):
        # table.name = nama tabel tanpa katalog/schema; jangan pakai str(table)
        # karena itu bisa "schema.table" atau "db.schema.table".
        names.add(table.name.lower())
    return names


def _has_dangerous_function(tree: exp.Expression) -> str | None:
    for func in tree.find_all(exp.Anonymous):
        if func.name.lower() in _DANGEROUS_FUNCTIONS:
            return func.name
    # sqlglot bisa memetakan beberapa fungsi ke kelas ekspresi khusus,
    # jadi cek juga semua Anonymous di atas sudah cukup untuk pg_sleep.
    return None


def validate_readonly_query(sql: str, allowed_tables: set[str]) -> None:
    """Validasi satu statement SELECT read-only terhadap whitelist tabel.

    Args:
        sql: teks query dari user/planner.
        allowed_tables: nama tabel (lowercase) yang boleh disentuh.

    Raises:
        SqlGuardError (ValueError): bila query melanggar kebijakan.
    """
    if not sql or not sql.strip():
        raise SqlGuardError("Query kosong")

    # --- Gerbang 1: parse tunggal, fail-closed ---
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except ParseError as e:
        raise SqlGuardError(f"SQL tidak bisa diparse: {e}") from e

    # buang None (sqlglot bisa menghasilkan None untuk ';')
    statements = [s for s in statements if s is not None]
    if not statements:
        raise SqlGuardError("Tidak ada statement yang bisa dievaluasi")
    if len(statements) > 1:
        raise SqlGuardError("Multi-statement tidak diizinkan")

    tree = statements[0]

    # --- Gerbang 2: read-only, SELECT tunggal di root ---
    if not isinstance(tree, exp.Select):
        kind = type(tree).__name__
        raise SqlGuardError(
            f"Hanya SELECT yang diizinkan (ditemukan: {kind})")

    # SELECT INTO menulis tabel baru — masih exp.Select, blokir eksplisit
    if tree.args.get("into"):
        raise SqlGuardError("SELECT INTO tidak diizinkan")

    # --- Gerbang 4: fungsi berbahaya (cek sebelum whitelist agar pesan jelas) ---
    dangerous = _has_dangerous_function(tree)
    if dangerous:
        raise SqlGuardError(f"Fungsi tidak diizinkan: {dangerous}")

    # --- Gerbang 3: whitelist tabel ---
    referenced = _extract_table_names(tree)
    allowed_lower = {t.lower() for t in allowed_tables}
    unknown = sorted(referenced - allowed_lower)
    if unknown:
        raise SqlGuardError(
            f"Tabel di luar whitelist: {', '.join(unknown)}")

    logger.debug("sql_guard: query lolos (%d tabel direferensikan)", len(referenced))
