"""Test query_executor (F2.4) — gerbang #6 eksekusi terkurung.

Tidak connect DB nyata: pool & koneksi tenant dipalsukan lewat fake yang
mencatat setiap panggilan (fetch/execute/transaction/prepare/cursor), sehingga
urutan READ ONLY + SET LOCAL statement_timeout + cap baris bisa diverifikasi.
pytest-asyncio tidak tersedia — skenario async dibungkus asyncio.run.
"""
import asyncio
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

try:
    from app.services.query_executor import (
        ExecutorError, execute_tenant_query, verify_and_execute,
        _konversi_nilai, _petakan_sql_eksekusi)
    from app.services.sql_composer import compose_sql, ganti_placeholder_null
    HAS_EXECUTOR = True
except ImportError:
    HAS_EXECUTOR = False

from conftest import SCHEMA_CONFIG_DEALER

SQL_MURAH = "SELECT merek FROM kendaraan WHERE tahun > 2023"
SQL_BERPARAM = "SELECT merek FROM kendaraan WHERE tahun = $1 LIMIT 10"


def _plan_explain(cost=100.0, rows=10):
    return [{"Plan": {"Node Type": "Seq Scan", "Total Cost": cost,
                      "Plan Rows": rows}}]


class FakeStmt:
    """Prepared statement palsu — nama kolom hasil get_attributes()."""

    def __init__(self, kolom=("merek",)):
        self.kolom = kolom

    def get_attributes(self):
        class _A:
            def __init__(self, name):
                self.name = name
        return [_A(k) for k in self.kolom]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    async def fetch(self, n):
        self.conn.fetch_n.append(n)
        return self.conn.hasil[:n]


class FakeConn:
    """Koneksi tenant palsu: mencatat urutan panggilan & hasil fetch."""

    def __init__(self, hasil=None, explain_error=None, kolom=("merek",)):
        self.hasil = hasil or []
        self.explain_error = explain_error
        self.kolom = kolom
        self.catatan = []
        self.fetch_n = []

    async def fetch(self, sql, *args):
        self.catatan.append(("fetch", sql))
        if self.explain_error is not None:
            raise self.explain_error
        return [(json.dumps(_plan_explain()),)]

    async def execute(self, sql):
        self.catatan.append(("execute", sql))

    def transaction(self, readonly=False):
        self.catatan.append(("transaction", {"readonly": readonly}))
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def prepare(self, sql):
        self.catatan.append(("prepare", sql))
        return FakeStmt(self.kolom)

    def cursor(self, sql, *args):
        # meniru asyncpg CursorFactory: awaitable -> Cursor
        self.catatan.append(("cursor", sql, args))
        fake = FakeCursor(self)

        class _AwaitableCursor:
            def __await__(self):
                if False:
                    yield
                return fake
        return _AwaitableCursor()


class FakePool:
    def __init__(self, conn):
        self.conn = conn
        self.release_count = 0

    async def acquire(self):
        return self.conn

    async def release(self, conn):
        self.release_count += 1


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.skipif(not HAS_EXECUTOR, reason="query_executor belum ada")
class TestVerdictGate:
    def test_verdict_gagal_tidak_dieksekusi(self):
        # tabel halusinasi -> gerbang whitelist; JANGAN sampai eksekusi jalan
        conn = FakeConn()
        pool = FakePool(conn)
        out = _run(verify_and_execute(pool, "SELECT * FROM tabel_hantu",
                                      SCHEMA_CONFIG_DEALER))
        assert out["verdict"]["ok"] is False
        assert out["verdict"]["gate"] == "whitelist"
        assert out["result"] is None
        assert all(c[0] != "transaction" for c in conn.catatan)
        assert all(c[0] != "cursor" for c in conn.catatan)

    def test_verdict_lolos_menghasilkan_result(self):
        conn = FakeConn(hasil=[("Avanza",), ("Xenia",)])
        out = _run(verify_and_execute(FakePool(conn), SQL_MURAH,
                                      SCHEMA_CONFIG_DEALER))
        assert out["verdict"]["ok"] is True
        assert out["result"]["row_count"] == 2
        assert out["result"]["columns"] == ["merek"]

    def test_verifier_gates_dijalankan_pada_teks_null_substitusi(self):
        # kontrak F2.2: SQL berparameter diverifikasi lewat ganti_placeholder_null
        conn = FakeConn()
        _run(verify_and_execute(FakePool(conn), SQL_BERPARAM,
                                SCHEMA_CONFIG_DEALER, params=[2024]))
        fetches = [c[1] for c in conn.catatan if c[0] == "fetch"]
        assert len(fetches) == 1
        assert "EXPLAIN (FORMAT JSON)" in fetches[0]
        assert "= NULL" in fetches[0] and "$1" not in fetches[0]


@pytest.mark.skipif(not HAS_EXECUTOR, reason="query_executor belum ada")
class TestEksekusiTerhung:
    def test_readonly_dan_statement_timeout_ter_set(self):
        conn = FakeConn(hasil=[("x",)])
        _run(execute_tenant_query(FakePool(conn), SQL_MURAH))
        urutan = [c[0] for c in conn.catatan]
        assert urutan.index("transaction") < urutan.index("execute")
        assert ("transaction", {"readonly": True}) in conn.catatan
        assert ("execute", "SET LOCAL statement_timeout = '10s'") in conn.catatan

    def test_sql_asli_dieksekusi_bukan_versi_null(self):
        # dengan params: prepare/cursor menerima SQL berparameter asli
        conn = FakeConn(hasil=[("x",)])
        _run(verify_and_execute(FakePool(conn), SQL_BERPARAM,
                                SCHEMA_CONFIG_DEALER, params=[2024]))
        prepares = [c[1] for c in conn.catatan if c[0] == "prepare"]
        cursors = [c for c in conn.catatan if c[0] == "cursor"]
        assert prepares == [SQL_BERPARAM]
        assert cursors[0][1] == SQL_BERPARAM
        assert cursors[0][2] == (2024,)

    def test_map_ast_parameter_ke_null(self):
        # bukti struktural: Parameter->Null pada SQL asli == teks cek
        final = ganti_placeholder_null(SQL_BERPARAM)
        assert _petakan_sql_eksekusi(SQL_BERPARAM, final, [2024]) == SQL_BERPARAM

    def test_map_fail_closed_bila_struktur_diubah(self):
        final = ganti_placeholder_null(SQL_BERPARAM)
        with pytest.raises(ExecutorError):
            _petakan_sql_eksekusi(SQL_BERPARAM.replace("merek", "model"),
                                  final, [2024])

    def test_sql_berparameter_tanpa_params_ditolak(self):
        conn = FakeConn()
        with pytest.raises(ExecutorError):
            _run(execute_tenant_query(FakePool(conn), SQL_BERPARAM))
        assert conn.catatan == []  # tidak menyentuh transaksi sama sekali

    def test_row_cap_truncated(self):
        conn = FakeConn(hasil=[(i,) for i in range(501)])
        out = _run(execute_tenant_query(FakePool(conn), SQL_MURAH, row_cap=500))
        assert out["truncated"] is True
        assert out["row_count"] == 500
        assert conn.fetch_n == [501]  # cursor berhenti di cap+1

    def test_row_cap_kecil_custom(self):
        conn = FakeConn(hasil=[(i,) for i in range(5)])
        out = _run(execute_tenant_query(FakePool(conn), SQL_MURAH, row_cap=2))
        assert out["truncated"] is True
        assert out["row_count"] == 2
        assert conn.fetch_n == [3]

    def test_tidak_truncated(self):
        conn = FakeConn(hasil=[(1,), (2,)])
        out = _run(execute_tenant_query(FakePool(conn), SQL_MURAH))
        assert out["truncated"] is False
        assert out["row_count"] == 2

    def test_hasil_kosong_kolom_dari_prepare(self):
        conn = FakeConn(hasil=[], kolom=("merek", "tahun"))
        out = _run(execute_tenant_query(FakePool(conn), SQL_MURAH))
        assert out["columns"] == ["merek", "tahun"]
        assert out["rows"] == []

    def test_durasi_ms_tercatat(self):
        conn = FakeConn(hasil=[(1,)])
        out = _run(execute_tenant_query(FakePool(conn), SQL_MURAH))
        assert isinstance(out["duration_ms"], int) and out["duration_ms"] >= 0


@pytest.mark.skipif(not HAS_EXECUTOR, reason="query_executor belum ada")
class TestKonversiJSON:
    def test_decimal_date_datetime(self):
        assert _konversi_nilai(Decimal("245000000.5")) == 245000000.5
        assert _konversi_nilai(date(2026, 9, 1)) == "2026-09-01"
        assert (_konversi_nilai(datetime(2026, 9, 1, 7, 30))
                == "2026-09-01T07:30:00")

    def test_timedelta_uuid_bytes(self):
        assert _konversi_nilai(timedelta(hours=2)) == "2:00:00"
        u = uuid.uuid4()
        assert _konversi_nilai(u) == str(u)
        assert _konversi_nilai(b"teks") == "teks"
        assert _konversi_nilai(b"\xff") == "ff"  # hex fallback

    def test_scalar_dan_rekursif(self):
        assert _konversi_nilai(None) is None
        assert _konversi_nilai(True) is True
        assert _konversi_nilai([Decimal("1.5"), date(2026, 1, 1)]) == [1.5, "2026-01-01"]

    def test_baris_decimal_dan_date_lewat_eksekusi(self):
        conn = FakeConn(hasil=[(Decimal("1000000"), date(2026, 9, 1))],
                        kolom=("total", "tanggal"))
        out = _run(execute_tenant_query(FakePool(conn), SQL_MURAH))
        assert out["rows"] == [[1000000.0, "2026-09-01"]]


@pytest.mark.skipif(not HAS_EXECUTOR, reason="query_executor belum ada")
class TestComposerIntegration:
    def test_compose_lalu_verify_and_execute_end_to_end_fake(self):
        # jalur persis seperti chat_pipeline: compose -> verify_and_execute
        plan = {
            "tables": ["penjualan"],
            "columns": [{"agg": "SUM", "column": "penjualan.harga_deal",
                         "alias": "total"}],
            "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},
        }
        from datetime import datetime
        composed = compose_sql(plan, SCHEMA_CONFIG_DEALER,
                               now=datetime(2026, 9, 1))
        conn = FakeConn(hasil=[(Decimal("9000000"),)], kolom=("total",))
        out = _run(verify_and_execute(FakePool(conn), composed["sql"],
                                      SCHEMA_CONFIG_DEALER,
                                      params=composed["params"]))
        assert out["verdict"]["ok"] is True
        assert out["result"]["rows"] == [[9000000.0]]
        # EXPLAIN pada teks NULL, eksekusi pada teks $n
        assert "NULL" in conn.catatan[0][1]
        assert "$1" in [c[1] for c in conn.catatan if c[0] == "prepare"][0]
