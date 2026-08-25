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
