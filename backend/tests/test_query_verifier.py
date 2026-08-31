"""
Test query_verifier (F2.3') - gerbang #5 EXPLAIN pre-flight.

Tidak connect DB nyata: koneksi tenant dipalsukan lewat tenant_conn_factory
(async callable yang mengembalikan fake conn dengan fetch()). pytest-asyncio
tidak tersedia, jadi skenario async dibungkus asyncio.run di test sinkron.
"""
import asyncio
import json

import pytest

try:
    from app.services import query_verifier
    from app.services.query_verifier import verify_query
    HAS_VERIFIER = True
except ImportError:
    HAS_VERIFIER = False

from conftest import SCHEMA_CONFIG_DEALER

SQL_MURAH = "SELECT merek FROM kendaraan WHERE tahun > 2023"


def _plan(cost=100.0, rows=10):
    """Bentuk output EXPLAIN (FORMAT JSON) palsu."""
    return [{"Plan": {"Node Type": "Seq Scan", "Total Cost": cost,
                      "Plan Rows": rows}}]


class FakeConn:
    """Koneksi tenant palsu: fetch() mengembalikan baris EXPLAIN."""

    def __init__(self, plan=None, error=None, output=None):
        self.plan = plan if plan is not None else _plan()
        self.error = error
        self.output = output  # bentuk baris mentah; default: string JSON
        self.query_dipanggil = []

    async def fetch(self, sql, *args):
        self.query_dipanggil.append(sql)
        if self.error is not None:
            raise self.error
        if self.output is not None:
            return self.output
        return [(json.dumps(self.plan),)]


def _factory(conn, pencatat):
    async def buat_koneksi():
        pencatat.append("dibuka")
        return conn
    return buat_koneksi


@pytest.mark.skipif(not HAS_VERIFIER, reason="query_verifier belum diimplementasikan (F2.3')")
class TestQueryVerifier:
    def test_query_murah_lolos_dengan_estimasi(self):
        conn = FakeConn(_plan(cost=250.5, rows=42))
        pencatat = []
        verdict = asyncio.run(verify_query(
            SQL_MURAH, SCHEMA_CONFIG_DEALER, _factory(conn, pencatat)))
        assert verdict["ok"] is True
        assert verdict["gate"] is None
        assert verdict["detail"]["explain"] == {"total_cost": 250.5, "plan_rows": 42}
        # EXPLAIN dijalankan pada SQL final (LIMIT sudah dipaksa)
        assert len(conn.query_dipanggil) == 1
        assert conn.query_dipanggil[0].startswith("EXPLAIN (FORMAT JSON)")
        assert "LIMIT 500" in conn.query_dipanggil[0]
        assert pencatat == ["dibuka"]

    def test_cost_besar_ditolak(self):
        conn = FakeConn(_plan(cost=1_000_000.0, rows=10))
        verdict = asyncio.run(verify_query(
            SQL_MURAH, SCHEMA_CONFIG_DEALER, _factory(conn, [])))
        print(f"\n[F2.3'] VERDICT gerbang #5: {verdict}")
        assert verdict["ok"] is False
        assert verdict["gate"] == "explain"
        assert "cost" in verdict["reason"].lower()

    def test_rows_besar_ditolak(self):
        conn = FakeConn(_plan(cost=50.0, rows=10_000_000))
        verdict = asyncio.run(verify_query(
            SQL_MURAH, SCHEMA_CONFIG_DEALER, _factory(conn, [])))
        assert verdict["ok"] is False
        assert verdict["gate"] == "explain"
        assert "baris" in verdict["reason"].lower()

    def test_explain_error_ditolak_default_deny(self):
        # SQL sah secara parse tapi salah semantik terhadap DB -> TOLAK
        conn = FakeConn(error=RuntimeError("column harga_x does not exist"))
        verdict = asyncio.run(verify_query(
            SQL_MURAH, SCHEMA_CONFIG_DEALER, _factory(conn, [])))
        assert verdict["ok"] is False
        assert verdict["gate"] == "explain"
        assert "EXPLAIN gagal" in verdict["reason"]

    def test_sql_lolos_offline_tapi_salah_sintaks_db_ditolak(self):
        # "SELECT" polos lolos gerbang offline (ter-parse) tapi postgres
        # menolak saat EXPLAIN — bukti gerbang #5 sebagai lapisan kedua
        conn = FakeConn(error=RuntimeError('syntax error at or near ";"'))
        verdict = asyncio.run(verify_query(
            "SELECT", SCHEMA_CONFIG_DEALER, _factory(conn, [])))
        assert verdict["ok"] is False
        assert verdict["gate"] == "explain"

    def test_explain_output_rusak_ditolak(self):
        conn = FakeConn(output=[("bukan json",)])
        verdict = asyncio.run(verify_query(
            SQL_MURAH, SCHEMA_CONFIG_DEALER, _factory(conn, [])))
        assert verdict["ok"] is False
        assert verdict["gate"] == "explain"
        assert "tidak terbaca" in verdict["reason"]

    def test_explain_sudah_dicoded_list(self):
        # bila codec json aktif, asyncpg bisa memberi list (bukan string)
        conn = FakeConn(output=[(_plan(cost=10.0, rows=1),)])
        verdict = asyncio.run(verify_query(
            SQL_MURAH, SCHEMA_CONFIG_DEALER, _factory(conn, [])))
        assert verdict["ok"] is True

    def test_gerbang_offline_gagal_explain_tidak_dipanggil(self):
        conn = FakeConn()  # kalau dipanggil, query_dipanggil berisi 1
        verdict = asyncio.run(verify_query(
            "SELECT * FROM stok_gudang",  # tabel halusinasi -> whitelist
            SCHEMA_CONFIG_DEALER, _factory(conn, [])))
        assert verdict["ok"] is False
        assert verdict["gate"] == "whitelist"
        assert conn.query_dipanggil == []  # EXPLAIN TIDAK pernah dijalankan

    def test_kb_forbidden_diteruskan_ke_guard(self):
        conn = FakeConn()
        verdict = asyncio.run(verify_query(
            "SELECT * FROM service_records", SCHEMA_CONFIG_DEALER,
            _factory(conn, []), kb_forbidden=["service_records"]))
        assert verdict["ok"] is False
        assert verdict["gate"] == "whitelist"
        assert conn.query_dipanggil == []

    def test_konstanta_budget_explain(self):
        # nilai default yang disepakati (dokumentasi keputusan teknis)
        assert query_verifier.EXPLAIN_MAX_COST == 100_000.0
        assert query_verifier.EXPLAIN_MAX_ROWS == 500_000

    def test_verdict_ok_membawa_final_sql_untuk_executor(self):
        # kontrak F2.4: final_sql siap dieksekusi, verifier berhenti di keputusan
        conn = FakeConn()
        verdict = asyncio.run(verify_query(
            SQL_MURAH, SCHEMA_CONFIG_DEALER, _factory(conn, [])))
        assert verdict["ok"] is True
        assert verdict["detail"]["final_sql"].upper().count("SELECT") >= 1
        assert verdict["reason"] == "lolos semua gerbang offline"
