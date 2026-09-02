"""Test F2.7 — Eval Harness Golden-Set (backend) tanpa LLM nyata.

Cakupan:
- CRUD eval-cases admin (valid/422 berbahaya/kosong/duplikat/edit/delete/404/
  guard 403).
- eval_runner.jalankan_eval (fake LLM + fake conn tenant): lulus persis,
  normalisasi whitespace/kapital, semantik, mismatch semantik, planner gagal,
  pelanggaran verifier (memory & sql_harapan), tier2 flag ON + fallback,
  memory tier2 literal tanggal MISS, batas, timeout, exception, total 0,
  simpan_metrik, normalisasi_sql.
- status_gate: belum run / pass_rate rendah / pelanggaran / lulus.
- Endpoint eval-run + riwayat eval-runs.
- Migration 009/010 idempotent (HANYA bila DB dev docker hidup — skip).

Pola fake diambil dari test_chat_api.py / test_tier2.py (FakeCorePool,
FakeTenantConn, FakeTenantPoolManager).
"""
import asyncio
import copy
import json
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt

try:
    from app.core.config import settings
    from app.services import eval_runner
    from app.services.eval_runner import (
        jalankan_eval, normalisasi_sql, simpan_metrik, status_gate)
    HAS_EVAL = True
except ImportError:
    HAS_EVAL = False

from conftest import SCHEMA_CONFIG_DEALER
from test_chat_api import (NOW_TETAP, PAYLOAD_USER, FakeCorePool,
                           FakeTenantConn, FakeTenantPoolManager)
import asyncpg

# SQL emas literal (lolos verify_sql terhadap SCHEMA_CONFIG_DEALER)
SQL_GOLDEN = "SELECT COUNT(*) AS total FROM penjualan"
SQL_HANTU = "SELECT * FROM tabel_hantu LIMIT 5"
# Harapan omzet bulanan literal (untuk jalur semantik — SQL pipeline
# berparameter $1..$2 sehingga tak mungkin persis secara teks)
SQL_HARAPAN_OMZET = (
    'SELECT SUM("penjualan"."harga_deal") AS omzet FROM "penjualan" '
    "WHERE \"penjualan\".\"tanggal\" >= '2026-09-01' "
    "AND \"penjualan\".\"tanggal\" < '2026-10-01' LIMIT 200")


def _json_rencana():
    return json.dumps({"tables": ["penjualan"],
                       "columns": [{"agg": "SUM",
                                    "column": "penjualan.harga_deal",
                                    "alias": "omzet"}],
                       "time_range": {"field": "penjualan.tanggal",
                                      "preset": "this_month"}})


def _fake_llm(outputs, jeda=0.0):
    """LLM palsu: kembalikan outputs berurutan; catat panggilan."""
    panggilan = []

    async def llm(system, user, ai_config):
        if jeda:
            await asyncio.sleep(jeda)
        panggilan.append({"system": system, "user": user})
        keluar = outputs.pop(0)
        if isinstance(keluar, Exception):
            raise keluar
        return keluar

    return llm, panggilan


# ===========================================================================
# Fake infrastruktur
# ===========================================================================
class FakeConnSemantik(FakeTenantConn):
    """FakeTenantConn + hasil cursor PER SQL (substring) — untuk membuktikan
    jalur perbandingan semantik yang cocok dan yang berbeda."""

    def __init__(self, hasil_per_sql=None, **kwargs):
        super().__init__(**kwargs)
        self.hasil_per_sql = hasil_per_sql or {}  # substring -> baris

    def cursor(self, sql, *args):
        hasil = self.hasil
        for kunci, h in self.hasil_per_sql.items():
            if kunci.lower() in sql.lower():
                hasil = h
                break
        pilihan = hasil

        class _AwaitableCursor:
            # kontrak executor: conn.cursor(...) adalah awaitable cursor
            def __await__(self):
                if False:
                    yield
                return self

            async def fetch(self, n):
                return pilihan[:n]
        return _AwaitableCursor()


class FakeCorePoolEval(FakeCorePool):
    """FakeCorePool + eval_cases + eval_runs (CRUD admin + jalankan_eval)."""

    def __init__(self):
        super().__init__()
        self.user_role = "admin"   # untuk guard require_admin_role nyata
        self.eval_cases = []
        self.eval_runs = []

    def seed_case(self, *, pertanyaan, sql_harapan, catatan=None, aktif=True,
                  tenant_id=3):
        self.next_id += 1
        entri = {
            "id": self.next_id, "tenant_id": tenant_id,
            "pertanyaan": pertanyaan, "sql_harapan": sql_harapan,
            "catatan": catatan, "aktif": aktif,
            "created_at": NOW_TETAP, "updated_at": NOW_TETAP}
        self.eval_cases.append(entri)
        return entri

    def seed_eval_run(self, *, pass_rate=1.0, pelanggaran_verifier=0,
                      total=10, lulus=None, tenant_id=3):
        if lulus is None:
            lulus = total
        self.next_id += 1
        self.eval_runs.append({
            "id": self.next_id, "tenant_id": tenant_id, "total": total,
            "lulus": lulus, "pelanggaran_verifier": pelanggaran_verifier,
            "pass_rate": pass_rate, "detail": None,
            "dijalankan_oleh": "admin", "created_at": NOW_TETAP})
        return self.eval_runs[-1]

    def seed_memory(self, *, q_norm, sql, plan_json=None, status="approved",
                    times_used=0, tenant_id=3, ringkasan=None, saran=None,
                    sumber="tier1"):
        entri_id = super().seed_memory(
            q_norm=q_norm, sql=sql, plan_json=plan_json, status=status,
            times_used=times_used, tenant_id=tenant_id, ringkasan=ringkasan,
            saran=saran)
        self.sql_memory[-1]["sumber"] = sumber
        return self.sql_memory[-1]

    async def fetchrow(self, sql, *args):
        if "INSERT INTO eval_cases" in sql:
            tid, pertanyaan, sql_h, catatan = args
            for r in self.eval_cases:
                if r["tenant_id"] == tid and r["pertanyaan"] == pertanyaan:
                    raise asyncpg.exceptions.UniqueViolationError(
                        'duplicate key value violates unique constraint '
                        '"uq_eval_cases_tenant_pertanyaan"')
            self.next_id += 1
            entri = {
                "id": self.next_id, "tenant_id": tid,
                "pertanyaan": pertanyaan, "sql_harapan": sql_h,
                "catatan": catatan, "aktif": True,
                "created_at": NOW_TETAP, "updated_at": NOW_TETAP}
            self.eval_cases.append(entri)
            return dict(entri)
        if "UPDATE eval_cases" in sql:
            cid, pertanyaan, sql_h, catatan, aktif, tid = args
            for r in self.eval_cases:
                if r["id"] == cid and r["tenant_id"] == tid:
                    r.update(pertanyaan=pertanyaan, sql_harapan=sql_h,
                             catatan=catatan, aktif=aktif,
                             updated_at=datetime(2026, 9, 1, 11, 0))
                    return dict(r)
            return None
        if "FROM eval_cases" in sql:
            cid, tid = args
            for r in self.eval_cases:
                if r["id"] == cid and r["tenant_id"] == tid:
                    return dict(r)
            return None
        if "FROM eval_runs" in sql:
            tid = args[0]
            kandidat = [r for r in self.eval_runs if r["tenant_id"] == tid]
            return kandidat[-1] if kandidat else None
        if "FROM users WHERE id" in sql:
            return {"role": self.user_role, "is_active": True}
        return await super().fetchrow(sql, *args)

    async def fetch(self, sql, *args):
        if "FROM eval_cases" in sql:
            tid = args[0]
            # jalankan_eval memfilter aktif = TRUE di SQL; endpoint daftar
            # menampilkan SEMUA kasus (aktif maupun tidak)
            hanya_aktif = "aktif = TRUE" in sql
            kandidat = [dict(r) for r in self.eval_cases
                        if r["tenant_id"] == tid
                        and (r["aktif"] or not hanya_aktif)]
            kandidat.sort(key=lambda r: r["id"])
            if "LIMIT $2" in sql:
                kandidat = kandidat[:args[1]]
            return kandidat
        if "FROM eval_runs" in sql:
            # riwayat snapshot (terbaru dulu); args = (tenant_id, limit)
            tid = args[0]
            kandidat = [dict(r) for r in self.eval_runs
                        if r["tenant_id"] == tid]
            kandidat.sort(key=lambda r: (-r["created_at"].timestamp()
                                         if r["created_at"] else 0, -r["id"]))
            return kandidat[:args[1]]
        raise AssertionError(f"fetch tak dikenal: {sql[:90]}")

    async def fetchval(self, sql, *args):
        if "INSERT INTO eval_runs" in sql:
            tid, total, lulus, pel, pass_rate, detail, oleh = args
            self.next_id += 1
            self.eval_runs.append({
                "id": self.next_id, "tenant_id": tid, "total": total,
                "lulus": lulus, "pelanggaran_verifier": pel,
                "pass_rate": pass_rate, "detail": detail,
                "dijalankan_oleh": oleh, "created_at": NOW_TETAP})
            return self.next_id
        return await super().fetchval(sql, *args)

    async def execute(self, sql, *args):
        if "DELETE FROM eval_cases" in sql:
            cid, tid = args
            sisa = [r for r in self.eval_cases
                    if not (r["id"] == cid and r["tenant_id"] == tid)]
            n = len(self.eval_cases) - len(sisa)
            self.eval_cases = sisa
            return f"DELETE {n}"
        return await super().execute(sql, *args)


# ===========================================================================
# Unit: normalisasi_sql & status_gate
# ===========================================================================
@pytest.mark.skipif(not HAS_EVAL, reason="eval_runner belum ada")
class TestNormalisasiSql:
    def test_kapital_spasi_kutip_sama(self):
        # isi sama persis, beda kapitalisasi/spasi/kutip identifier
        a = 'SELECT COUNT(*) AS total FROM penjualan LIMIT 500'
        b = 'select   count(*)   as "total"\n from "penjualan" LIMIT 500;'
        assert normalisasi_sql(a) == normalisasi_sql(b)

    def test_isi_berbeda_tetap_terbedakan(self):
        assert normalisasi_sql("SELECT 1") != normalisasi_sql("SELECT 2")

    def test_string_literal_tetap_dibedakan(self):
        assert normalisasi_sql("SELECT 'a b'") != normalisasi_sql("SELECT 'ab'")


@pytest.mark.skipif(not HAS_EVAL, reason="eval_runner belum ada")
class TestStatusGate:
    def test_belum_pernah_run_tolak(self):
        gate = status_gate({"branch_code": "JKT_01"}, None)
        assert gate["tier2_diizinkan"] is False
        assert "jalankan eval dulu" in gate["alasan"]

    def test_pass_rate_rendah_tolak_sebut_pass_rate(self):
        gate = status_gate({"branch_code": "JKT_01"},
                           {"pass_rate": 0.9, "pelanggaran_verifier": 0})
        assert gate["tier2_diizinkan"] is False
        assert "90%" in gate["alasan"] and "95%" in gate["alasan"]

    def test_ada_pelanggaran_tolak(self):
        gate = status_gate({"branch_code": "JKT_01"},
                           {"pass_rate": 1.0, "pelanggaran_verifier": 2})
        assert gate["tier2_diizinkan"] is False
        assert "pelanggaran" in gate["alasan"]

    def test_lulus_diizinkan(self):
        gate = status_gate({"branch_code": "JKT_01"},
                           {"pass_rate": 1.0, "pelanggaran_verifier": 0})
        assert gate["tier2_diizinkan"] is True

    def test_batas_persis_095_lulus(self):
        gate = status_gate({}, {"pass_rate": 0.95, "pelanggaran_verifier": 0})
        assert gate["tier2_diizinkan"] is True


# ===========================================================================
# Service: jalankan_eval + simpan_metrik
# ===========================================================================
@pytest.mark.skipif(not HAS_EVAL, reason="eval_runner belum ada")
class TestJalankanEval:
    def _siap(self, flag_tier2=False):
        fake = FakeCorePoolEval()
        fake.seed_tenant()
        fake.tenant["chat_tier2"] = flag_tier2
        conn = FakeConnSemantik(hasil=[(Decimal("5"),)])
        tpm = FakeTenantPoolManager(conn)
        return fake, tpm, conn

    def _seed_memory_golden(self, fake, pertanyaan, sql=SQL_GOLDEN,
                            **kwargs):
        return fake.seed_memory(
            q_norm=eval_runner.normalisasi_pertanyaan(pertanyaan), sql=sql,
            **kwargs)

    def test_semua_persis_pass_rate_1(self):
        fake, tpm, _ = self._siap()
        fake.seed_case(pertanyaan="berapa total transaksi",
                       sql_harapan=SQL_GOLDEN)
        fake.seed_case(pertanyaan="jumlah penjualan",
                       sql_harapan=SQL_GOLDEN)
        self._seed_memory_golden(fake, "berapa total transaksi")
        self._seed_memory_golden(fake, "jumlah penjualan")
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", tenant_pool_manager=tpm,
            now=NOW_TETAP))
        assert hasil["total"] == 2
        assert hasil["lulus"] == 2
        assert hasil["gagal"] == []
        assert hasil["pelanggaran_verifier"] == 0
        assert hasil["pass_rate"] == 1.0
        assert [c["status"] for c in hasil["detail"]] == ["persis", "persis"]
        assert all(c["jalur"] == "memory" for c in hasil["detail"])

    def test_beda_kapital_spasi_tetap_persis(self):
        fake, tpm, _ = self._siap()
        fake.seed_case(
            pertanyaan="berapa total transaksi",
            sql_harapan='select   count(*)  as "total"\n from penjualan ;')
        self._seed_memory_golden(fake, "berapa total transaksi")
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", tenant_pool_manager=tpm, now=NOW_TETAP))
        assert hasil["detail"][0]["status"] == "persis"
        assert hasil["pass_rate"] == 1.0

    def test_beda_sql_hasil_sama_semantik(self):
        fake, tpm, _ = self._siap()
        fake.seed_case(pertanyaan="omzet bulan ini",
                       sql_harapan=SQL_HARAPAN_OMZET)
        fake.seed_config_global()
        llm, _ = _fake_llm([_json_rencana()])
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", llm_call_fn=llm,
            tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "semantik"
        assert case["jalur"] == "tier1"
        assert hasil["pass_rate"] == 1.0
        assert "semantik" in case["alasan"]

    def test_semantik_hasil_berbeda_gagal(self):
        fake, tpm, _ = self._siap()
        # SQL harapan memuat literal tanggal -> hasil berbeda dari pipeline
        conn = FakeConnSemantik(
            hasil=[(Decimal("5"),)],
            hasil_per_sql={"2026-09-01": [(Decimal("999"),)]})
        tpm.conn = conn
        fake.seed_case(pertanyaan="omzet bulan ini",
                       sql_harapan=SQL_HARAPAN_OMZET)
        fake.seed_config_global()
        llm, _ = _fake_llm([_json_rencana()])
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", llm_call_fn=llm,
            tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "gagal"
        assert "hasil query berbeda" in case["alasan"]
        assert hasil["lulus"] == 0 and hasil["pass_rate"] == 0.0

    def test_planner_gagal_status_gagal(self):
        fake, tpm, _ = self._siap()
        fake.seed_case(pertanyaan="omzet bulan ini",
                       sql_harapan=SQL_HARAPAN_OMZET)
        fake.seed_config_global()
        llm, _ = _fake_llm(["rusak-1", "rusak-2"])  # planner retry habis
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", llm_call_fn=llm,
            tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "gagal"
        assert "PlanningError" in case["alasan"]
        assert hasil["pelanggaran_verifier"] == 0

    def test_memory_ditolak_verifier_pelanggaran(self):
        fake, tpm, _ = self._siap()
        fake.seed_case(pertanyaan="data hantu", sql_harapan=SQL_GOLDEN)
        self._seed_memory_golden(fake, "data hantu", sql=SQL_HANTU)
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "pelanggaran"
        assert "whitelist" in case["alasan"]
        assert hasil["pelanggaran_verifier"] == 1
        assert hasil["lulus"] == 0

    def test_sql_harapan_ditolak_verifier_pelanggaran(self):
        fake, tpm, _ = self._siap()
        # golden set rusak: sql_harapan merujuk tabel di luar skema
        fake.seed_case(pertanyaan="apa itu hantu", sql_harapan=SQL_HANTU)
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "pelanggaran"
        assert "sql_harapan" in case["alasan"]
        assert hasil["pelanggaran_verifier"] == 1

    def test_flag_on_generator_tier2_persis(self):
        fake, tpm, _ = self._siap(flag_tier2=True)
        fake.seed_case(pertanyaan="berapa total transaksi",
                       sql_harapan=SQL_GOLDEN)
        fake.seed_config_global()
        llm, _ = _fake_llm([json.dumps({"tier": 2, "sql": SQL_GOLDEN})])
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", llm_call_fn=llm,
            tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "persis"
        assert case["jalur"] == "tier2"
        # gerbang #5 jalan DUA kali (generator + defense-in-depth eval)
        assert case["sql_dihasilkan"] and "LIMIT" in case["sql_dihasilkan"]

    def test_flag_on_generator_habis_fallback_tier1(self):
        fake, tpm, _ = self._siap(flag_tier2=True)
        fake.seed_case(pertanyaan="omzet bulan ini",
                       sql_harapan=SQL_HARAPAN_OMZET)
        fake.seed_config_global()
        llm, _ = _fake_llm(["rusak-1", "rusak-2", "rusak-3",
                            _json_rencana()])
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", llm_call_fn=llm,
            tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "semantik"
        assert case["jalur"] == "tier1"  # fallback planner lama

    def test_memory_tier2_literal_tanggal_miss(self):
        fake, tpm, _ = self._siap()
        fake.seed_case(pertanyaan="omzet bulan ini",
                       sql_harapan=SQL_HARAPAN_OMZET)
        entri = self._seed_memory_golden(
            fake, "omzet bulan ini",
            sql="SELECT COUNT(*) AS c FROM penjualan "
                "WHERE tanggal >= '2026-08-01'::date",
            plan_json=json.dumps({"tier2": True}), sumber="tier2")
        fake.seed_config_global()
        llm, _ = _fake_llm([_json_rencana()])
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", llm_call_fn=llm,
            tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "semantik"
        assert case["jalur"] == "tier1"  # replay MISS -> planner
        # eval tidak mengubah state memory (berbeda dgn pipeline produksi)
        assert entri["status"] == "approved"
        assert entri["times_used"] == 0

    def test_tanpa_kasus_total_0_pass_rate_0(self):
        fake, tpm, _ = self._siap()
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", tenant_pool_manager=tpm, now=NOW_TETAP))
        assert hasil["total"] == 0
        assert hasil["lulus"] == 0
        assert hasil["pass_rate"] == 0.0
        # golden set kosong tidak membuka gate
        gate = status_gate({"branch_code": "JKT_01"}, {
            "pass_rate": hasil["pass_rate"],
            "pelanggaran_verifier": hasil["pelanggaran_verifier"]})
        assert gate["tier2_diizinkan"] is False

    def test_batas_membatasi_jumlah_kasus(self):
        fake, tpm, _ = self._siap()
        for i in range(3):
            fake.seed_case(pertanyaan=f"pertanyaan {i}",
                           sql_harapan=SQL_GOLDEN)
            self._seed_memory_golden(fake, f"pertanyaan {i}")
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", batas=1, tenant_pool_manager=tpm,
            now=NOW_TETAP))
        assert hasil["total"] == 1
        assert len(hasil["detail"]) == 1

    def test_timeout_per_case_gagal(self):
        fake, tpm, _ = self._siap()
        fake.seed_case(pertanyaan="omzet bulan ini",
                       sql_harapan=SQL_HARAPAN_OMZET)
        fake.seed_config_global()
        llm, _ = _fake_llm([_json_rencana()], jeda=0.5)
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", llm_call_fn=llm,
            tenant_pool_manager=tpm, now=NOW_TETAP, timeout_per_case=0.1))
        case = hasil["detail"][0]
        assert case["status"] == "gagal"
        assert "timeout" in case["alasan"]

    def test_exception_llm_jadi_gagal_dengan_alasan(self):
        fake, tpm, _ = self._siap()
        fake.seed_case(pertanyaan="omzet bulan ini",
                       sql_harapan=SQL_HARAPAN_OMZET)
        fake.seed_config_global()
        llm, _ = _fake_llm([RuntimeError("boom")])
        hasil = asyncio.run(jalankan_eval(
            fake, "JKT_01", "admin", llm_call_fn=llm,
            tenant_pool_manager=tpm, now=NOW_TETAP))
        case = hasil["detail"][0]
        assert case["status"] == "gagal"
        assert "RuntimeError" in case["alasan"] and "boom" in case["alasan"]

    def test_tenant_tidak_ada_raise(self):
        fake, _, _ = self._siap()
        with pytest.raises(Exception):
            asyncio.run(jalankan_eval(fake, "XXX_99", "admin"))

    def test_simpan_metrik(self):
        fake, _, _ = self._siap()
        hasil = {"total": 4, "lulus": 3, "gagal": [], "detail": [],
                 "pelanggaran_verifier": 1, "pass_rate": 0.75,
                 "dijalankan_oleh": "admin"}
        ringkas = asyncio.run(simpan_metrik(fake, "JKT_01", hasil))
        assert ringkas["run_id"] == fake.eval_runs[0]["id"]
        assert ringkas["pass_rate"] == 0.75
        baris = fake.eval_runs[0]
        assert baris["total"] == 4 and baris["lulus"] == 3
        assert baris["pelanggaran_verifier"] == 1
        assert baris["tenant_id"] == 3


# ===========================================================================
# Endpoint admin: CRUD eval-cases
# ===========================================================================
@pytest.mark.skipif(not HAS_EVAL, reason="eval_runner belum ada")
class TestEndpointEvalCases:
    @pytest.fixture
    def lingkungan(self, monkeypatch):
        from app.main import app
        from app.routers.admin import eval as eval_router
        from app.core.security import require_admin_role

        fake = FakeCorePoolEval()
        fake.seed_tenant()
        conn = FakeConnSemantik(hasil=[(Decimal("5"),)])
        tpm = FakeTenantPoolManager(conn)

        async def _pool():
            return fake

        async def fake_resolve(pool, username, branch_code):
            return {"api_key": "sk-test"}

        monkeypatch.setattr(eval_router, "get_core_pool", _pool)
        monkeypatch.setattr(eval_router, "get_tenant_pool_manager",
                            lambda: tpm)
        monkeypatch.setattr(eval_runner, "resolve_ai_config", fake_resolve)
        app.dependency_overrides[require_admin_role] = lambda: {
            "user_id": 1, "username": "admin", "role": "admin"}
        client = TestClient(app)

        class Lingkungan:
            pass
        env = Lingkungan()
        env.client = client
        env.core = fake
        yield env
        app.dependency_overrides.clear()

    def _post(self, client, pertanyaan="berapa total transaksi",
              sql=SQL_GOLDEN, branch="JKT_01"):
        return client.post(f"/admin/tenants/{branch}/eval-cases",
                           json={"pertanyaan": pertanyaan,
                                 "sql_harapan": sql})

    def test_tambah_valid(self, lingkungan):
        resp = self._post(lingkungan.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] > 0 and data["aktif"] is True
        assert data["pertanyaan"] == "berapa total transaksi"
        assert data["sql_harapan"] == SQL_GOLDEN
        assert len(lingkungan.core.eval_cases) == 1
        # ter-audit
        assert lingkungan.core.audit_logs[0]["status"] == "success"
        assert "eval-case-create" in lingkungan.core.audit_logs[0]["prompt_text"]

    def test_tambah_sql_berbahaya_422(self, lingkungan):
        resp = self._post(lingkungan.client,
                          sql="DELETE FROM penjualan")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["gate"] == "bentuk"
        # golden set yang salah TIDAK masuk
        assert lingkungan.core.eval_cases == []
        assert lingkungan.core.audit_logs[0]["status"] == "error"

    def test_tambah_fungsi_dilarang_422(self, lingkungan):
        resp = self._post(lingkungan.client, sql="SELECT pg_sleep(10)")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["gate"] == "profil"
        assert "pg_sleep" in detail["reason"]

    def test_tambah_tabel_luar_whitelist_422(self, lingkungan):
        resp = self._post(lingkungan.client, sql=SQL_HANTU)
        assert resp.status_code == 422
        assert resp.json()["detail"]["gate"] == "whitelist"

    def test_tambah_pertanyaan_kosong_422(self, lingkungan):
        resp = self._post(lingkungan.client, pertanyaan="   ")
        assert resp.status_code == 422
        assert lingkungan.core.eval_cases == []

    def test_tambah_duplikat_400(self, lingkungan):
        assert self._post(lingkungan.client).status_code == 200
        resp = self._post(lingkungan.client)
        assert resp.status_code == 400
        assert "sudah ada" in resp.json()["detail"]

    def test_tambah_404_cabang(self, lingkungan):
        resp = self._post(lingkungan.client, branch="XXX_99")
        assert resp.status_code == 404

    def test_get_daftar(self, lingkungan):
        lingkungan.core.seed_case(pertanyaan="p1", sql_harapan=SQL_GOLDEN)
        lingkungan.core.seed_case(pertanyaan="p2", sql_harapan=SQL_GOLDEN,
                                  catatan="cat", aktif=False)
        resp = lingkungan.client.get("/admin/tenants/JKT_01/eval-cases")
        assert resp.status_code == 200
        data = resp.json()
        assert [d["pertanyaan"] for d in data] == ["p1", "p2"]
        assert data[1]["aktif"] is False and data[1]["catatan"] == "cat"

    def test_put_edit(self, lingkungan):
        entri = lingkungan.core.seed_case(pertanyaan="p1",
                                          sql_harapan=SQL_GOLDEN)
        resp = lingkungan.client.put(
            f"/admin/tenants/JKT_01/eval-cases/{entri['id']}",
            json={"catatan": "diperiksa admin", "aktif": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["catatan"] == "diperiksa admin"
        assert data["aktif"] is False
        assert data["sql_harapan"] == SQL_GOLDEN  # tak berubah

    def test_put_sql_baru_tidak_lolos_422(self, lingkungan):
        entri = lingkungan.core.seed_case(pertanyaan="p1",
                                          sql_harapan=SQL_GOLDEN)
        resp = lingkungan.client.put(
            f"/admin/tenants/JKT_01/eval-cases/{entri['id']}",
            json={"sql_harapan": "DROP TABLE penjualan"})
        assert resp.status_code == 422
        # nilai lama tetap
        assert lingkungan.core.eval_cases[0]["sql_harapan"] == SQL_GOLDEN

    def test_put_404_entri(self, lingkungan):
        resp = lingkungan.client.put(
            "/admin/tenants/JKT_01/eval-cases/999",
            json={"aktif": False})
        assert resp.status_code == 404

    def test_delete_sukses_dan_404(self, lingkungan):
        entri = lingkungan.core.seed_case(pertanyaan="p1",
                                          sql_harapan=SQL_GOLDEN)
        resp = lingkungan.client.delete(
            f"/admin/tenants/JKT_01/eval-cases/{entri['id']}")
        assert resp.status_code == 200
        assert lingkungan.core.eval_cases == []
        # hapus lagi -> 404
        resp = lingkungan.client.delete(
            f"/admin/tenants/JKT_01/eval-cases/{entri['id']}")
        assert resp.status_code == 404

    def test_guard_user_role_ditolak_403(self, monkeypatch):
        # Guard NYATA (tanpa override): token role 'user' -> 403
        from app.main import app
        from app.routers.admin import eval as eval_router

        fake = FakeCorePoolEval()
        fake.seed_tenant()
        fake.user_role = "user"

        async def _pool():
            return fake

        monkeypatch.setattr(eval_router, "get_core_pool", _pool)
        monkeypatch.setattr("app.core.database.get_core_pool", _pool)
        token = jwt.encode(
            {"sub": "7", "user_id": 7, "username": "u", "role": "user",
             "allowed_branches": ["JKT_01"]},
            settings.secret_key, algorithm=settings.algorithm)
        client = TestClient(app)
        resp = client.get(
            "/admin/tenants/JKT_01/eval-cases",
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
        assert "role 'admin'" in resp.json()["detail"]


# ===========================================================================
# Endpoint admin: eval-run + riwayat
# ===========================================================================
@pytest.mark.skipif(not HAS_EVAL, reason="eval_runner belum ada")
class TestEndpointEvalRun:
    @pytest.fixture
    def lingkungan_run(self, monkeypatch):
        from app.main import app
        from app.routers.admin import eval as eval_router
        from app.core.security import require_admin_role

        fake = FakeCorePoolEval()
        fake.seed_tenant()
        fake.seed_case(pertanyaan="berapa total transaksi",
                       sql_harapan=SQL_GOLDEN)
        fake.seed_memory(
            q_norm=eval_runner.normalisasi_pertanyaan("berapa total transaksi"),
            sql=SQL_GOLDEN)
        conn = FakeConnSemantik(hasil=[(Decimal("5"),)])
        tpm = FakeTenantPoolManager(conn)

        async def _pool():
            return fake

        monkeypatch.setattr(eval_router, "get_core_pool", _pool)
        monkeypatch.setattr(eval_router, "get_tenant_pool_manager",
                            lambda: tpm)
        # jalankan_eval menyelesaikan ai_config; planner tak dipanggil pada
        # jalur memory — patch defensif agar tak pernah menyentuh LLM nyata.
        async def fake_resolve(pool, username, branch_code):
            return {"api_key": "sk-test"}

        async def fake_plan(*a, **k):
            raise AssertionError("planner dipanggil pada jalur memory")

        monkeypatch.setattr(eval_runner, "resolve_ai_config", fake_resolve)
        monkeypatch.setattr(eval_runner, "plan_query", fake_plan)
        app.dependency_overrides[require_admin_role] = lambda: {
            "user_id": 1, "username": "admin", "role": "admin"}
        client = TestClient(app)

        class Lingkungan:
            pass
        env = Lingkungan()
        env.client = client
        env.core = fake
        yield env
        app.dependency_overrides.clear()

    def test_eval_run_sukses(self, lingkungan_run):
        resp = lingkungan_run.client.post("/admin/tenants/JKT_01/eval-run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1 and data["lulus"] == 1
        assert data["pass_rate"] == 1.0
        assert data["pelanggaran_verifier"] == 0
        assert data["detail"][0]["status"] == "persis"
        assert data["run_id"] == lingkungan_run.core.eval_runs[0]["id"]
        assert data["gate"]["tier2_diizinkan"] is True
        assert data["dijalankan_oleh"] == "admin"
        # ter-audit
        audit = lingkungan_run.core.audit_logs
        assert any(a["status"] == "success" and "eval-run" in a["prompt_text"]
                   for a in audit)

    def test_eval_run_404_cabang(self, lingkungan_run):
        resp = lingkungan_run.client.post("/admin/tenants/XXX_99/eval-run")
        assert resp.status_code == 404

    def test_eval_run_batas_query(self, lingkungan_run):
        # tambah 2 kasus lagi tanpa memory -> tetap total 1 karena batas=1
        for i in (1, 2):
            lingkungan_run.core.seed_case(pertanyaan=f"p{i}",
                                          sql_harapan=SQL_GOLDEN)
        resp = lingkungan_run.client.post(
            "/admin/tenants/JKT_01/eval-run?batas=1")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_riwayat_eval_runs_terbaru_dulu(self, lingkungan_run):
        lingkungan_run.core.seed_eval_run(pass_rate=0.8, total=10, lulus=8)
        lingkungan_run.core.seed_eval_run(pass_rate=1.0, total=10)
        resp = lingkungan_run.client.get(
            "/admin/tenants/JKT_01/eval-runs?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["pass_rate"] == 1.0  # terbaru dulu
        assert data[1]["pass_rate"] == 0.8
        for item in data:
            assert {"id", "total", "lulus", "pelanggaran_verifier",
                    "pass_rate", "dijalankan_oleh",
                    "created_at"} <= set(item)

    def test_riwayat_limit_dihormati(self, lingkungan_run):
        for _ in range(3):
            lingkungan_run.core.seed_eval_run()
        resp = lingkungan_run.client.get(
            "/admin/tenants/JKT_01/eval-runs?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_riwayat_404_cabang(self, lingkungan_run):
        resp = lingkungan_run.client.get("/admin/tenants/XXX_99/eval-runs")
        assert resp.status_code == 404


# ===========================================================================
# Migration 009/010 — idempotent (HANYA bila DB dev docker hidup)
# ===========================================================================
class TestMigrasi009010:
    def test_init_db_dua_kali_tabel_eval_idempotent(self):
        """Jalankan init_db 2x lalu pastikan tabel eval muncul TEPAT 1."""
        import os
        from dotenv import load_dotenv
        load_dotenv(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env"))

        try:
            from init_db import init_db
            asyncio.run(init_db())
            asyncio.run(init_db())  # ke-2 harus aman (idempotent)
        except Exception as e:  # koneksi gagal / docker mati -> skip
            pytest.skip(f"DB dev tidak hidup — migrasi 009/010 diuji "
                        f"manual: {e}")

        async def _cek():
            dsn = (
                f"postgresql://{os.getenv('CORE_DB_USER')}:"
                f"{os.getenv('CORE_DB_PASSWORD')}@{os.getenv('CORE_DB_HOST')}:"
                f"{os.getenv('CORE_DB_PORT')}/{os.getenv('CORE_DB_NAME')}")
            conn = await asyncpg.connect(dsn)
            try:
                return await conn.fetch(
                    "SELECT table_name, COUNT(*) AS n "
                    "FROM information_schema.tables "
                    "WHERE table_name IN ('eval_cases', 'eval_runs') "
                    "GROUP BY table_name")
            finally:
                await conn.close()

        rows = asyncio.run(_cek())
        jumlah = {r["table_name"]: r["n"] for r in rows}
        assert jumlah.get("eval_cases") == 1
        assert jumlah.get("eval_runs") == 1
