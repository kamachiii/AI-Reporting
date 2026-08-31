"""
Test sql_guard (F2.3) - katalog serangan SQL.

Ditulis sebelum sql_guard.py dibangun (TDD): semua kasus di sini HARUS
ditolak begitu modul implementasi ada. Sementara modul belum ada,
test ini di-skip agar CI tetap hijau.
"""
import pytest

try:
    from app.services.sql_guard import validate_readonly_query
    HAS_SQL_GUARD = True
except ImportError:
    HAS_SQL_GUARD = False

ALLOWED_TABLES = {"kendaraan", "pelanggan", "penjualan", "detail_penjualan", "service_records"}

ATTACKS = [
    "DROP TABLE penjualan",
    "DELETE FROM penjualan",
    "UPDATE penjualan SET harga = 0",
    "INSERT INTO penjualan VALUES (1)",
    "TRUNCATE TABLE penjualan",
    "SELECT 1; DROP TABLE penjualan",              # multi-statement
    "SELECT * FROM information_schema.tables",      # di luar whitelist
    "SELECT pg_sleep(10)",                          # DoS
    "SELECT * FROM penjualan UNION SELECT * FROM pg_catalog.pg_tables",
]

LEGITIMATE = [
    "SELECT merek, COUNT(*) FROM penjualan GROUP BY merek",
    "SELECT * FROM kendaraan WHERE tahun > 2020 LIMIT 50",
]


@pytest.mark.skipif(not HAS_SQL_GUARD, reason="sql_guard belum diimplementasikan (F2.3)")
class TestSqlGuard:
    @pytest.mark.parametrize("sql", ATTACKS)
    def test_attacks_rejected(self, sql):
        with pytest.raises(Exception):
            validate_readonly_query(sql, ALLOWED_TABLES)

    @pytest.mark.parametrize("sql", LEGITIMATE)
    def test_legitimate_pass(self, sql):
        # Tidak melempar exception = valid
        validate_readonly_query(sql, ALLOWED_TABLES)

    # ---- LIMIT policy (docs pipeline §4: paksa LIMIT <= 500) ----

    @pytest.mark.parametrize("sql", [
        "SELECT merek, COUNT(*) FROM penjualan GROUP BY merek LIMIT 500",
        "SELECT * FROM kendaraan WHERE tahun > 2020 LIMIT 1",
    ])
    def test_limit_within_cap_pass(self, sql):
        validate_readonly_query(sql, ALLOWED_TABLES)

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM penjualan LIMIT 501",
        "SELECT * FROM penjualan LIMIT 10000",
        "SELECT merek FROM penjualan GROUP BY merek LIMIT 999999999",
    ])
    def test_limit_over_cap_rejected(self, sql):
        with pytest.raises(Exception):
            validate_readonly_query(sql, ALLOWED_TABLES)

    def test_no_limit_gets_default(self):
        # Query tanpa LIMIT tidak lagi lolos begitu saja:
        # guard menambahkan LIMIT 500 secara otomatis dan mengembalikan SQL final.
        result = validate_readonly_query("SELECT merek FROM penjualan", ALLOWED_TABLES)
        assert isinstance(result, str)
        final = result.upper().replace(" ", "")
        assert "LIMIT500" in final or "LIMIT'500'" in final or "LIMIT500" in final.replace("'", "")
        # dan SQL final tetap bisa di-parse
        import sqlglot
        sqlglot.parse_one(result, read="postgres")
