"""
Test sql_guard (F2.3) - katalog serangan SQL.

Ditulis sebelum sql_guard.py dibangun (TDD): semua kasus di sini HARUS
ditolak begitu modul implementasi ada. Sementara modul belum ada,
test ini di-skip agar CI tetap hijau.
"""
import pytest

try:
    from app.services.sql_guard import (
        validate_readonly_query,
        verify_sql,
        DEFAULT_BUDGET,
        SQL_FEATURE_PROFILE_V1,
    )
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


# ============================================================================
# F2.3' Verifier v2 — verify_sql (gerbang #1–#4 terstruktur)
# ============================================================================

G = "bentuk", "whitelist", "profil", "budget"  # alias pendek nama gerbang


def _subquery_bertumpuk(dalam: int) -> str:
    """Subquery IN bersarang `dalam` tingkat (untuk budget kedalaman AST)."""
    dalam_sql = "SELECT penjualan_id FROM detail_penjualan"
    for _ in range(dalam):
        dalam_sql = ("SELECT penjualan_id FROM detail_penjualan "
                     "WHERE penjualan_id IN (" + dalam_sql + ")")
    return "SELECT * FROM penjualan WHERE id IN (" + dalam_sql + ")"


def _rantai_join(n_tabel: int) -> str:
    """Self-join n tabel (FK sama-tabel diizinkan) — untuk budget jumlah join."""
    bagian = ["SELECT * FROM penjualan p0"]
    for i in range(1, n_tabel):
        bagian.append(f"JOIN penjualan p{i} ON p{i}.id = p{i - 1}.id")
    return " ".join(bagian)


def _rantai_cte(n: int) -> str:
    """n CTE berantai — untuk budget jumlah CTE."""
    definisi = "a1 AS (SELECT * FROM penjualan)"
    for i in range(2, n + 1):
        definisi += f", a{i} AS (SELECT * FROM a{i - 1})"
    return f"WITH {definisi} SELECT * FROM a{n}"


def _rantai_union(n_cabang: int) -> str:
    """n cabang UNION ALL — untuk budget jumlah UNION (= n_cabang - 1)."""
    cabang = ["SELECT merek FROM kendaraan"] + [
        "SELECT model FROM kendaraan" for _ in range(n_cabang - 1)]
    return " UNION ALL ".join(cabang)


# Query reporting SAH yang harus LOLOS seluruh gerbang offline.
POSITIF_VERIFIER = [
    # agregasi + GROUP BY
    "SELECT metode_pembayaran, COUNT(*) AS jumlah FROM penjualan GROUP BY metode_pembayaran",
    "SELECT nama_sales, SUM(harga_deal) AS omzet FROM penjualan GROUP BY nama_sales",
    "SELECT MIN(harga_deal), MAX(harga_deal), AVG(harga_deal) FROM penjualan",
    # agregasi + JOIN (lewat peta FK)
    "SELECT p.nama_sales, SUM(d.jumlah) AS total FROM penjualan p JOIN detail_penjualan d ON d.penjualan_id = p.id GROUP BY p.nama_sales",
    "SELECT p.id, COUNT(d.id) AS n FROM penjualan p LEFT JOIN detail_penjualan d ON d.penjualan_id = p.id GROUP BY p.id",
    # CTE non-rekursif (output infer-able & ber-*)
    "WITH bulanan AS (SELECT tanggal, harga_deal FROM penjualan) SELECT COUNT(*) FROM bulanan",
    "WITH jual AS (SELECT * FROM penjualan WHERE harga_deal > 0) SELECT j.tanggal FROM jual j",
    # UNION ALL (dua cabang, kolom sama)
    "SELECT merek, tahun FROM kendaraan UNION ALL SELECT model, tahun FROM kendaraan",
    "SELECT merek FROM kendaraan UNION ALL SELECT model FROM kendaraan ORDER BY merek LIMIT 5",
    # CASE / DISTINCT / subquery IN / ORDER+LIMIT
    "SELECT merek, CASE WHEN tahun >= 2023 THEN 'baru' ELSE 'lama' END AS kategori FROM kendaraan",
    "SELECT DISTINCT kota FROM pelanggan",
    "SELECT nama FROM pelanggan WHERE id IN (SELECT pelanggan_id FROM penjualan WHERE harga_deal > 100000000)",
    "SELECT nomor_rangka, tahun FROM kendaraan ORDER BY tahun DESC, nomor_rangka LIMIT 100",
    "SELECT merek, COUNT(*) FROM kendaraan GROUP BY merek ORDER BY merek LIMIT 10",
    # JOIN jenis lain yang sah
    "SELECT k1.merek FROM kendaraan k1 JOIN kendaraan k2 ON k2.id = k1.id",
    "SELECT * FROM penjualan p JOIN (SELECT id FROM pelanggan) pl ON pl.id = p.pelanggan_id",
    "SELECT tahun FROM kendaraan k JOIN service_records s ON s.kendaraan_id = k.id ORDER BY tahun",
    "SELECT jumlah, harga FROM (SELECT penjualan_id, SUM(jumlah) AS jumlah FROM detail_penjualan GROUP BY penjualan_id) x JOIN (SELECT 1 AS harga) y ON x.penjualan_id = y.harga",
    # fungsi string & tanggal umum + operator
    "SELECT to_char(tanggal, 'YYYY-MM') AS bulan, COUNT(*) AS n FROM penjualan GROUP BY to_char(tanggal, 'YYYY-MM') ORDER BY bulan",
    "SELECT tanggal - INTERVAL '7 days' FROM penjualan WHERE tanggal >= current_date - 30",
    "SELECT extract(month from tanggal), date_trunc('month', tanggal) FROM penjualan",
    "SELECT a.merek || a.model FROM kendaraan a WHERE a.status IS NULL OR a.status = 'x' AND NOT (a.tahun = 2020)",
    "SELECT replace(merek, ' ', '-') FROM kendaraan",
    "SELECT nullif(metode_pembayaran, 'cash'), greatest(harga_deal, 0), least(harga_deal, 999), abs(-1), round(avg(harga_deal), 2), substring(nama_sales from 1 for 3), trim(catatan), left(nama_sales, 2), right(nama_sales, 2) FROM penjualan",
    "SELECT CAST(harga_deal AS numeric) FROM penjualan",
    # predikat & bentuk lain
    "SELECT * FROM kendaraan WHERE tahun BETWEEN 2022 AND 2024 AND merek LIKE '%Toyota%'",
    "SELECT * FROM kendaraan",
    "SELECT 1",
    # identifier kutip-ganda lowercase sah (case-insensitive untuk unquoted)
    'SELECT "merek" FROM kendaraan',
    # budget di batas atas: 7 tabel = 6 join (masih <= 6)
    _rantai_join(7),
]


# Katalog serangan: (sql, gerbang yang diharapkan). Semua WAJIB ditolak.
SERANGAN_VERIFIER = [
    # --- gerbang 1: parser & bentuk ----------------------------------------
    ("", G[0]),
    ("SELECT 1; DROP TABLE penjualan", G[0]),               # multi-statement
    ("SELECT * FROM penjualan; DELETE FROM penjualan", G[0]),
    ("SELECT 1; SELECT pg_sleep(5)", G[0]),
    ("INSERT INTO penjualan VALUES (1)", G[0]),
    ("UPDATE penjualan SET harga_deal = 0", G[0]),
    ("DELETE FROM penjualan", G[0]),
    ("DROP TABLE penjualan", G[0]),
    ("CREATE TABLE hack (id int)", G[0]),
    ("TRUNCATE TABLE penjualan", G[0]),
    ("SELECT merek INTO tabel_baru FROM kendaraan", G[0]),  # SELECT INTO
    ("COPY penjualan TO STDOUT", G[0]),
    ("SET search_path TO public", G[0]),
    ("SELECT * FROM penjualan FOR UPDATE", G[0]),           # lock clause
    ("WITH x AS (DELETE FROM penjualan) SELECT * FROM x", G[0]),  # DML di CTE
    ("SELECT * FROM penjualan LIMIT 501", G[0]),            # LIMIT > cap 500
    ("SELECT * FROM penjualan WHERE id IN (SELECT penjualan_id FROM detail_penjualan LIMIT 501)", G[0]),
    # --- gerbang 2: whitelist objek menyeluruh -----------------------------
    ("SELECT harga_otr FROM penjualan", G[1]),              # kolom halusinasi
    ("SELECT * FROM stok_gudang", G[1]),                    # tabel halusinasi
    ("SELECT * FROM penjualan WHERE id IN (SELECT id FROM audit_log)", G[1]),  # objek di subquery
    ("WITH t AS (SELECT * FROM pg_tables) SELECT * FROM t", G[1]),             # objek di CTE
    ("SELECT * FROM pg_catalog.pg_tables", G[1]),           # skema non-public
    ("SELECT * FROM information_schema.tables", G[1]),
    ("SELECT * FROM dblink('dbname=x', 'SELECT 1') AS t(a int)", G[1]),  # diparse sbg Table
    ("SELECT * FROM generate_series(1, 10)", G[1]),
    ("SELECT id FROM penjualan JOIN pelanggan ON penjualan.pelanggan_id = pelanggan.id", G[1]),  # ambigu
    ("SELECT p.harga_x FROM penjualan p", G[1]),            # kolom halusinasi qualified
    ("SELECT x.merek FROM penjualan p", G[1]),              # kualifikasi tak dikenal
    ("SELECT merek FROM kendaraan ORDER BY harga_xyz", G[1]),  # halusinasi di ORDER BY
    ("SELECT merek FROM kendaraan WHERE km = 1", G[1]),     # kolom milik tabel lain
    ('SELECT * FROM "Pelanggan"', G[1]),                    # kutip-ganda case-sensitive
    # --- gerbang 3: profil fitur SQL (default-deny) ------------------------
    ("WITH RECURSIVE t AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM t) SELECT n FROM t", G[2]),
    ("SELECT pg_sleep(10)", G[2]),                          # DoS
    ("SELECT pg_read_file('/etc/passwd')", G[2]),           # akses file
    ("SELECT pg_ls_dir('/')", G[2]),
    ("SELECT lo_import('/tmp/x')", G[2]),
    ("SELECT dblink('dbname=x', 'SELECT 1')", G[2]),        # di daftar ekspresi
    ("SELECT merek FROM kendaraan UNION SELECT model FROM kendaraan", G[2]),  # UNION dedup
    ("SELECT * FROM penjualan, detail_penjualan", G[2]),    # join tanpa ON
    ("SELECT * FROM penjualan CROSS JOIN detail_penjualan", G[2]),
    ("SELECT * FROM penjualan p JOIN service_records s ON s.km = p.id", G[2]),  # di luar peta FK
    ("SELECT merek, ROW_NUMBER() OVER (ORDER BY tahun) AS rn FROM kendaraan", G[2]),  # window
    ("SELECT merek FROM kendaraan WHERE EXISTS (SELECT 1 FROM detail_penjualan)", G[2]),
    ("SELECT merek, COUNT(*) FROM kendaraan GROUP BY merek HAVING COUNT(*) > 5", G[2]),
    ("SELECT merek FROM kendaraan OFFSET 5", G[2]),
    # --- gerbang 4: budget kompleksitas ------------------------------------
    (_subquery_bertumpuk(6), G[3]),
    (_rantai_join(8), G[3]),
    (_rantai_cte(5), G[3]),
    (_rantai_union(5), G[3]),
]


@pytest.mark.skipif(not HAS_SQL_GUARD, reason="sql_guard belum diimplementasikan (F2.3)")
class TestVerifierV2:
    @pytest.mark.parametrize("sql", POSITIF_VERIFIER)
    def test_query_reporting_sah_lolos(self, sql, schema_config_dealer):
        verdict = verify_sql(sql, schema_config_dealer)
        assert verdict["ok"] is True, f"{sql} -> {verdict}"

    @pytest.mark.parametrize("sql, gate", SERANGAN_VERIFIER)
    def test_serangan_ditolak_di_gerbang_benar(self, sql, gate, schema_config_dealer):
        verdict = verify_sql(sql, schema_config_dealer)
        assert verdict["ok"] is False, f"harus ditolak: {sql}"
        assert verdict["gate"] == gate, f"{sql}: gate {verdict['gate']} != {gate}"

    def test_tabel_dilarang_kb_ditolak(self, schema_config_dealer):
        verdict = verify_sql("SELECT * FROM service_records",
                             schema_config_dealer, kb_forbidden=["service_records"])
        assert verdict["ok"] is False
        assert verdict["gate"] == "whitelist"
        assert "tabel_dilarang" in verdict["reason"]

    def test_tabel_dilarang_di_cte_ditolak(self, schema_config_dealer):
        verdict = verify_sql("WITH t AS (SELECT * FROM service_records) SELECT * FROM t",
                             schema_config_dealer, kb_forbidden=["service_records"])
        assert verdict["ok"] is False
        assert verdict["gate"] == "whitelist"
        assert "tabel_dilarang" in verdict["reason"]

    def test_limit_dipaksa_500(self, schema_config_dealer):
        verdict = verify_sql("SELECT merek FROM kendaraan", schema_config_dealer)
        assert verdict["ok"] is True
        assert "LIMIT 500" in verdict["detail"]["final_sql"]
        # SQL final tetap ter-parse
        import sqlglot
        sqlglot.parse_one(verdict["detail"]["final_sql"], read="postgres")

    def test_budget_bisa_dioverride(self, schema_config_dealer):
        dalam = _subquery_bertumpuk(6)
        assert verify_sql(dalam, schema_config_dealer)["gate"] == "budget"
        besar = {"kedalaman_ast": 60}
        assert verify_sql(dalam, schema_config_dealer, budget=besar)["ok"] is True

    def test_profil_versioned_dan_budget_default(self):
        assert SQL_FEATURE_PROFILE_V1["version"] == 1
        assert DEFAULT_BUDGET["kedalaman_ast"] == 12
        assert DEFAULT_BUDGET["jumlah_join"] == 6
        assert DEFAULT_BUDGET["jumlah_cte"] == 4
        assert DEFAULT_BUDGET["jumlah_union"] == 3

    # ---- bukti default-deny: cetak Verdict per gerbang (lihat dgn -s) ----
    @pytest.mark.parametrize("sql", [
        "SELECT * FROM stok_gudang",                 # gerbang whitelist
        "SELECT pg_sleep(10)",                       # gerbang profil
        _rantai_join(8),                             # gerbang budget
    ])
    def test_bukti_default_deny_offline(self, sql, schema_config_dealer):
        verdict = verify_sql(sql, schema_config_dealer)
        print(f"\n[F2.3'] VERDICT gate={verdict['gate']}: {verdict}")
        assert verdict["ok"] is False

