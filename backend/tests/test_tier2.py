"""Test F2.6 bagian 1 — Tier 2 Verified Text2SQL (backend) tanpa DB nyata
dan tanpa LLM nyata.

Cakupan:
- Toggle admin POST /admin/tenants/{branch_code}/tier2 (on/off/404/guard).
- Generator tier2 (service murni + fake LLM + fake conn EXPLAIN murah):
  routing tier1/tier2, self-repair dengan umpan balik, Tier2Error.
- Integrasi chat_pipeline: flag OFF regresi, reuse compose hasil router
  tier1, jalur tier2 (source/confidence/attempts/memory/audit), fallback
  Tier2Error -> tier1, 502 gabungan, replay memory tier2 (aturan literal
  tanggal), bukti verifier tetap jalan di pipeline.
- Migration 008 idempotent (HANYA bila DB dev docker hidup — skip bila tidak).

Pola fake (FakeTenantConn/FakeTenantPool/FakeTenantPoolManager/FakeCorePool)
di-reuse dari test_chat_api.py — strategi yang sama, tanpa DB nyata.
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
    from app.services import chat_pipeline
    from app.services.chat_pipeline import normalisasi_pertanyaan, proses_pertanyaan
    from app.services.sql_composer import compose_sql
    from app.services.tier2_generator import MAX_ATTEMPTS_DEFAULT, Tier2Error, \
        generate_sql
    HAS_TIER2 = True
except ImportError:
    HAS_TIER2 = False

from conftest import SCHEMA_CONFIG_DEALER
from test_chat_api import (RENCANA, NOW_TETAP, PAYLOAD_USER, FakeCorePool,
                           FakeTenantConn, FakeTenantPoolManager)

# SQL tier2 valid terhadap SCHEMA_CONFIG_DEALER (verifier + EXPLAIN murah)
SQL_TIER2_VALID = "SELECT harga_deal FROM penjualan WHERE harga_deal > 100000000"


# ===========================================================================
# Fake infrastruktur tambahan
# ===========================================================================
class FakeCorePoolT2(FakeCorePool):
    """FakeCorePool + kolom tenants.chat_tier2 + endpoint toggle admin +
    eval_runs (F2.7 gate aktivasi Tier 2)."""

    def __init__(self):
        super().__init__()
        self.user_role = "admin"        # untuk guard require_admin_role
        self.updated_tier2 = None       # (branch_code, enabled) dari UPDATE
        self.eval_runs = []             # snapshot eval (gate tier2)

    def seed_tenant(self, chat_tier2=False):
        super().seed_tenant()
        self.tenant["chat_tier2"] = chat_tier2

    def seed_eval_run(self, *, pass_rate=1.0, pelanggaran_verifier=0,
                      total=20, lulus=None, tenant_id=3):
        """Seed snapshot eval_runs terpenuhi (gate tier2 lulus by default)."""
        if lulus is None:
            lulus = total
        self.next_id += 1
        from datetime import datetime as _dt
        self.eval_runs.append({
            "id": self.next_id, "tenant_id": tenant_id, "total": total,
            "lulus": lulus, "pelanggaran_verifier": pelanggaran_verifier,
            "pass_rate": pass_rate, "detail": None,
            "dijalankan_oleh": "admin",
            "created_at": _dt(2026, 9, 1, 10, 0)})
        return self.eval_runs[-1]

    async def fetchrow(self, sql, *args):
        if "FROM tenants WHERE branch_code" in sql:
            # F2.6 toggle: keberadaan tenant per cabang
            if self.tenant and self.tenant["branch_code"] == args[0]:
                return {"id": self.tenant["tenant_id"]}
            return None
        if "FROM eval_runs" in sql:
            # F2.7 gate: snapshot eval terbaru milik tenant (terbaru dulu)
            tenant_id = args[0]
            kandidat = [r for r in self.eval_runs
                        if r["tenant_id"] == tenant_id]
            return kandidat[-1] if kandidat else None
        if "FROM users WHERE id" in sql:
            return {"role": self.user_role, "is_active": True}
        return await super().fetchrow(sql, *args)

    async def execute(self, sql, *args):
        if "UPDATE tenants SET chat_tier2" in sql:
            self.updated_tier2 = args
            self.tenant["chat_tier2"] = args[1]
            return "UPDATE 1"
        return await super().execute(sql, *args)

    def seed_memory(self, *, q_norm, sql, plan_json=None, status="approved",
                    times_used=0, tenant_id=3, ringkasan=None, saran=None,
                    sumber="tier1"):
        entri_id = super().seed_memory(
            q_norm=q_norm, sql=sql, plan_json=plan_json, status=status,
            times_used=times_used, tenant_id=tenant_id, ringkasan=ringkasan,
            saran=saran)
        self.sql_memory[-1]["sumber"] = sumber
        return self.sql_memory[-1]


class FakeGenerator:
    """Pengganti tier2_generator.generate_sql di namespace chat_pipeline —

    memungkinkan test pipeline mengontrol keputusan router tanpa LLM.
    """

    def __init__(self, hasil=None, error=None):
        self.hasil = hasil
        self.error = error
        self.panggilan = []

    async def __call__(self, question, schema_config, kb, ai_config,
                       conn_factory, llm_call_fn=None,
                       max_attempts=MAX_ATTEMPTS_DEFAULT, now=None):
        self.panggilan.append({"question": question, "kb": kb,
                               "max_attempts": max_attempts})
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.hasil)

    def hasil_tier1_dari_compose(self, now=NOW_TETAP):
        """Hasil generator tier1 yang compose-nya benar-benar dijalankan."""
        composed = compose_sql(RENCANA, SCHEMA_CONFIG_DEALER, now=now)
        return {"tier": 1, "sql": composed["sql"],
                "params": composed["params"],
                "plan": copy.deepcopy(RENCANA), "attempts": 1}


def _fake_llm(outputs):
    """LLM palsu: kembalikan raw outputs berurutan; catat (system, user)."""
    panggilan = []

    async def llm(system, user, ai_config):
        panggilan.append({"system": system, "user": user})
        return outputs.pop(0)

    return llm, panggilan


def _conn_factory(conn):
    async def _factory():
        return conn
    return _factory


def _json_tier1(plan):
    return json.dumps({"tier": 1, "plan": plan})


def _json_tier2(sql):
    return json.dumps({"tier": 2, "sql": sql})


KB_KOSONG: dict = {}


# ===========================================================================
# Toggle admin
# ===========================================================================
@pytest.mark.skipif(not HAS_TIER2, reason="tier2 generator belum ada")
class TestToggleTier2:
    @pytest.fixture
    def lingkungan_admin(self, monkeypatch):
        from app.main import app
        from app.routers.admin import tenants as tenants_router

        fake_core = FakeCorePoolT2()
        fake_core.seed_tenant()

        async def _pool():
            return fake_core

        monkeypatch.setattr(tenants_router, "get_core_pool", _pool)
        from app.core.security import require_admin_role
        app.dependency_overrides[require_admin_role] = lambda: {
            "user_id": 1, "username": "admin", "role": "admin"}
        client = TestClient(app)

        class Lingkungan:
            pass
        env = Lingkungan()
        env.client = client
        env.core = fake_core
        yield env
        app.dependency_overrides.clear()

    def _post(self, client, branch="JKT_01", enabled=True):
        return client.post(f"/admin/tenants/{branch}/tier2",
                           json={"enabled": enabled})

    def test_toggle_on(self, lingkungan_admin):
        # F2.7: toggle ON melewati gate eval — seed snapshot lulus dulu.
        lingkungan_admin.core.seed_eval_run(pass_rate=1.0,
                                            pelanggaran_verifier=0)
        resp = self._post(lingkungan_admin.client, enabled=True)
        assert resp.status_code == 200
        assert resp.json() == {"branch_code": "JKT_01", "chat_tier2": True}
        # UPDATE parameterized terjadi dengan nilai yang benar
        assert lingkungan_admin.core.updated_tier2 == ("JKT_01", True)
        # ter-audit: 1 baris sukses bertanda tier2-toggle
        audit = lingkungan_admin.core.audit_logs
        assert len(audit) == 1
        assert audit[0]["status"] == "success"
        assert "tier2-toggle" in audit[0]["prompt_text"]
        assert audit[0]["user_id"] == 1

    def test_toggle_off_setelah_on(self, lingkungan_admin):
        lingkungan_admin.core.seed_eval_run(pass_rate=1.0,
                                            pelanggaran_verifier=0)
        assert self._post(lingkungan_admin.client, enabled=True).status_code == 200
        resp = self._post(lingkungan_admin.client, enabled=False)
        assert resp.status_code == 200
        assert resp.json()["chat_tier2"] is False
        assert lingkungan_admin.core.updated_tier2 == ("JKT_01", False)
        statuses = [a["status"] for a in lingkungan_admin.core.audit_logs]
        assert statuses == ["success", "success"]

    # ---------------- F2.7: gate eval pada toggle ON ----------------------
    def test_toggle_on_ditolak_belum_pernah_eval(self, lingkungan_admin):
        resp = self._post(lingkungan_admin.client, enabled=True)
        assert resp.status_code == 400
        assert "jalankan eval dulu" in resp.json()["detail"]
        assert lingkungan_admin.core.updated_tier2 is None  # flag tak berubah
        assert lingkungan_admin.core.tenant["chat_tier2"] is False
        # percobaan ditolak tetap ter-audit
        assert lingkungan_admin.core.audit_logs[0]["status"] == "error"

    def test_toggle_on_ditolak_pass_rate_rendah(self, lingkungan_admin):
        lingkungan_admin.core.seed_eval_run(pass_rate=0.9,
                                            pelanggaran_verifier=0)
        resp = self._post(lingkungan_admin.client, enabled=True)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "pass_rate" in detail and "90%" in detail
        assert "95%" in detail
        assert lingkungan_admin.core.updated_tier2 is None

    def test_toggle_on_ditolak_ada_pelanggaran(self, lingkungan_admin):
        # pass_rate penuh tetap ditolak bila ada pelanggaran verifier
        lingkungan_admin.core.seed_eval_run(pass_rate=1.0,
                                            pelanggaran_verifier=2)
        resp = self._post(lingkungan_admin.client, enabled=True)
        assert resp.status_code == 400
        assert "pelanggaran" in resp.json()["detail"]
        assert lingkungan_admin.core.updated_tier2 is None

    def test_toggle_off_tanpa_eval_tetap_boleh(self, lingkungan_admin):
        # mematikan flag tidak butuh gate
        resp = self._post(lingkungan_admin.client, enabled=False)
        assert resp.status_code == 200
        assert resp.json()["chat_tier2"] is False
        assert lingkungan_admin.core.updated_tier2 == ("JKT_01", False)

    def test_tenant_tak_ada_404_teraudit(self, lingkungan_admin):
        resp = self._post(lingkungan_admin.client, branch="XXX_99")
        assert resp.status_code == 404
        assert "tidak ditemukan" in resp.json()["detail"]
        # percobaan ditolak tetap ter-audit (jejak pensondelan)
        audit = lingkungan_admin.core.audit_logs
        assert len(audit) == 1
        assert audit[0]["status"] == "error"
        assert lingkungan_admin.core.updated_tier2 is None  # UPDATE tak jalan

    def test_guard_user_role_ditolak_403(self, monkeypatch):
        # Guard NYATA (tanpa override): token role 'user' -> 403
        from app.main import app
        from app.routers.admin import tenants as tenants_router

        fake_core = FakeCorePoolT2()
        fake_core.seed_tenant()
        fake_core.user_role = "user"

        async def _pool():
            return fake_core

        monkeypatch.setattr(tenants_router, "get_core_pool", _pool)
        monkeypatch.setattr("app.core.database.get_core_pool", _pool)
        token = jwt.encode(
            {"sub": "7", "user_id": 7, "username": "u", "role": "user",
             "allowed_branches": ["JKT_01"]},
            settings.secret_key, algorithm=settings.algorithm)
        client = TestClient(app)
        resp = client.post(
            "/admin/tenants/JKT_01/tier2", json={"enabled": True},
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
        assert "role 'admin'" in resp.json()["detail"]
        assert fake_core.updated_tier2 is None


# ===========================================================================
# Generator tier2 (service murni, fake LLM + fake conn)
# ===========================================================================
@pytest.mark.skipif(not HAS_TIER2, reason="tier2 generator belum ada")
class TestGeneratorTier2:
    def _conn(self, **kwargs):
        return FakeTenantConn(hasil=[(Decimal("850000000"),)], **kwargs)

    def test_tier1_plan_dikomposisi_tanpa_sentuh_db(self):
        llm, panggilan = _fake_llm([_json_tier1(RENCANA)])
        conn = self._conn()
        hasil = asyncio.run(generate_sql(
            "omzet bulan ini", SCHEMA_CONFIG_DEALER, KB_KOSONG,
            {"api_key": "k"}, _conn_factory(conn), llm_call_fn=llm,
            now=NOW_TETAP))
        assert hasil["tier"] == 1
        assert "SUM" in hasil["sql"] and "LIMIT" in hasil["sql"]
        assert len(hasil["params"]) == 2  # preset this_month -> 2 batas waktu
        assert hasil["plan"]["tables"] == ["penjualan"]
        assert hasil["attempts"] == 1
        # kontrak: jalur tier 1 TIDAK menyentuh koneksi DB tenant
        assert conn.catatan == []
        assert len(panggilan) == 1

    def test_tier2_sql_valid_verdict_ok(self):
        llm, _ = _fake_llm([_json_tier2("SELECT COUNT(*) AS total FROM penjualan")])
        conn = self._conn()
        hasil = asyncio.run(generate_sql(
            "berapa transaksi?", SCHEMA_CONFIG_DEALER, KB_KOSONG,
            {"api_key": "k"}, _conn_factory(conn), llm_call_fn=llm))
        assert hasil["tier"] == 2
        assert hasil["verdict"]["ok"] is True
        # SQL yang dikembalikan = final_sql verifier (LIMIT 500 dipaksa)
        assert "LIMIT" in hasil["sql"]
        assert hasil["attempts"] == 1
        # gerbang #5 (EXPLAIN) dijalankan lewat conn_factory
        assert any(c[0] == "fetch" and "EXPLAIN" in c[1] for c in conn.catatan)

    def test_json_rusak_retry_dengan_feedback_sukses(self):
        llm, panggilan = _fake_llm([
            "maaf, ini jawaban saya (bukan JSON)",
            _json_tier2(SQL_TIER2_VALID),
        ])
        hasil = asyncio.run(generate_sql(
            "omzet?", SCHEMA_CONFIG_DEALER, KB_KOSONG, {"api_key": "k"},
            _conn_factory(self._conn()), llm_call_fn=llm))
        assert hasil["tier"] == 2 and hasil["attempts"] == 2
        # percobaan ke-2 membawa umpan balik alasan penolakan
        assert "DITOLAK" in panggilan[1]["user"]
        assert "bukan JSON valid" in panggilan[1]["user"]

    def test_tier2_ditolak_verifier_feedback_gate_reason(self):
        llm, panggilan = _fake_llm([
            _json_tier2("SELECT * FROM tabel_hantu LIMIT 5"),
            _json_tier2(SQL_TIER2_VALID),
        ])
        hasil = asyncio.run(generate_sql(
            "data hantu?", SCHEMA_CONFIG_DEALER, KB_KOSONG, {"api_key": "k"},
            _conn_factory(self._conn()), llm_call_fn=llm))
        assert hasil["attempts"] == 2 and hasil["verdict"]["ok"] is True
        # feedback memuat gate + reason verifier (doktrin docs v2 §2)
        assert "whitelist" in panggilan[1]["user"]
        assert "tabel_hantu" in panggilan[1]["user"]

    def test_habis_percobaan_tier2error(self):
        llm, panggilan = _fake_llm([
            "rusak-1", "rusak-2", "rusak-3",
        ])
        with pytest.raises(Tier2Error) as exc:
            asyncio.run(generate_sql(
                "q", SCHEMA_CONFIG_DEALER, KB_KOSONG, {"api_key": "k"},
                _conn_factory(self._conn()), llm_call_fn=llm))
        # 1 percobaan + self-repair maks 2x (docs v2 §1)
        assert "3 percobaan" in str(exc.value)
        assert len(panggilan) == MAX_ATTEMPTS_DEFAULT == 3

    def test_pg_sleep_ditolak_repair_tetap_berbahaya_error(self):
        llm, panggilan = _fake_llm([
            _json_tier2("SELECT pg_sleep(10)"),
            _json_tier2("SELECT pg_sleep(10)"),
            _json_tier2("SELECT pg_sleep(10)"),
        ])
        with pytest.raises(Tier2Error) as exc:
            asyncio.run(generate_sql(
                "q", SCHEMA_CONFIG_DEALER, KB_KOSONG, {"api_key": "k"},
                _conn_factory(self._conn()), llm_call_fn=llm))
        assert "pg_sleep" in str(exc.value)
        # 1 percobaan + 2 self-repair, semuanya ditolak verifier
        assert len(panggilan) == 3

    def test_tier1_plan_invalid_feedback_retry_sukses(self):
        plan_rusak = {"tables": ["penjualan"],
                      "columns": ["penjualan.kolom_hantu"]}
        llm, panggilan = _fake_llm([
            _json_tier1(plan_rusak),
            _json_tier1(RENCANA),
        ])
        hasil = asyncio.run(generate_sql(
            "omzet?", SCHEMA_CONFIG_DEALER, KB_KOSONG, {"api_key": "k"},
            _conn_factory(self._conn()), llm_call_fn=llm, now=NOW_TETAP))
        assert hasil["tier"] == 1 and hasil["attempts"] == 2
        assert "rencana tidak valid" in panggilan[1]["user"]
        assert "kolom_hantu" in panggilan[1]["user"]

    def test_max_attempts_1_tanpa_retry(self):
        llm, panggilan = _fake_llm(["rusak"])
        with pytest.raises(Tier2Error):
            asyncio.run(generate_sql(
                "q", SCHEMA_CONFIG_DEALER, KB_KOSONG, {"api_key": "k"},
                _conn_factory(self._conn()), llm_call_fn=llm, max_attempts=1))
        assert len(panggilan) == 1

    def test_kb_tabel_dilarang_diteruskan_ke_verifier(self):
        kb = {"tabel_dilarang": ["service_records"]}
        llm, panggilan = _fake_llm([
            _json_tier2("SELECT biaya FROM service_records LIMIT 5"),
            _json_tier2(SQL_TIER2_VALID),
        ])
        hasil = asyncio.run(generate_sql(
            "biaya servis?", SCHEMA_CONFIG_DEALER, kb, {"api_key": "k"},
            _conn_factory(self._conn()), llm_call_fn=llm))
        assert hasil["attempts"] == 2 and hasil["verdict"]["ok"] is True
        assert "service_records" in panggilan[1]["user"]

    def test_field_hilang_tier2_retry(self):
        llm, _ = _fake_llm([
            json.dumps({"tier": 2}),  # 'sql' hilang
            _json_tier2(SQL_TIER2_VALID),
        ])
        hasil = asyncio.run(generate_sql(
            "q", SCHEMA_CONFIG_DEALER, KB_KOSONG, {"api_key": "k"},
            _conn_factory(self._conn()), llm_call_fn=llm))
        assert hasil["tier"] == 2 and hasil["attempts"] == 2


# ===========================================================================
# Integrasi chat_pipeline (flag OFF regresi + flag ON + memory replay tier2)
# ===========================================================================
@pytest.mark.skipif(not HAS_TIER2, reason="tier2 generator belum ada")
class TestPipelineTier2:
    @pytest.fixture
    def lingkungan_t2(self, monkeypatch):
        from app.main import app
        from app.routers import chat as chat_router
        from app.services import chat_pipeline

        fake_core = FakeCorePoolT2()
        fake_core.seed_tenant(chat_tier2=False)
        conn = FakeTenantConn(hasil=[(Decimal("850000000"),)])
        fake_tpm = FakeTenantPoolManager(conn)
        planner_catatan = []
        spy_generator = FakeGenerator(error=AssertionError(
            "generator dipanggil padahal seharusnya tidak"))

        async def _pool():
            return fake_core

        async def fake_plan_query(question, schema_config, kb, ai_config,
                                  llm_call_fn=None):
            planner_catatan.append(question)
            return copy.deepcopy(RENCANA)

        monkeypatch.setattr(chat_router, "get_core_pool", _pool)
        monkeypatch.setattr(chat_router, "get_tenant_pool_manager",
                            lambda: fake_tpm)
        monkeypatch.setattr(chat_router, "_chat_calls", defaultdict_deque())
        monkeypatch.setattr(chat_pipeline, "plan_query", fake_plan_query)
        monkeypatch.setattr(chat_pipeline, "generate_sql", spy_generator)
        app.dependency_overrides[require_user_role_override()] = lambda: dict(
            PAYLOAD_USER)
        client = TestClient(app)

        class Lingkungan:
            pass
        env = Lingkungan()
        env.client = client
        env.core = fake_core
        env.conn = conn
        env.tpm = fake_tpm
        env.planner_catatan = planner_catatan
        env.gen = spy_generator
        yield env
        app.dependency_overrides.clear()

    def _pasang_flag(self, lingkungan_t2, aktif):
        lingkungan_t2.core.tenant["chat_tier2"] = aktif

    def _pasang_generator(self, monkeypatch, lingkungan_t2, gen):
        from app.services import chat_pipeline
        monkeypatch.setattr(chat_pipeline, "generate_sql", gen)
        lingkungan_t2.gen = gen

    def _post(self, client, question="omzet bulan ini", branch="JKT_01"):
        return client.post("/chat/query", json={"question": question,
                                                "branch_code": branch})

    # ---------------- flag OFF: regresi alur lama -------------------------
    def test_flag_off_alur_lama_tanpa_generator(self, lingkungan_t2):
        # gen bawaan fixture melempar AssertionError bila dipanggil
        lingkungan_t2.core.seed_config_global()
        resp = self._post(lingkungan_t2.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "tier1" and data["confidence"] == "B"
        assert lingkungan_t2.planner_catatan == ["omzet bulan ini"]
        assert "attempts" not in data  # kontrak lama tanpa field baru

    def test_flag_off_memory_tier2_bertanggal_miss_jalur_tier1(
            self, lingkungan_t2):
        # entri tier2 approved berliteral tanggal -> MISS (tak replay basi),
        # baris tetap disimpan; flag OFF -> regenerasi lewat planner lama
        entri = lingkungan_t2.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT COUNT(*) AS c FROM penjualan "
                "WHERE tanggal >= '2026-08-01'::date",
            plan_json=json.dumps({"tier2": True}), sumber="tier2")
        lingkungan_t2.core.seed_config_global()
        resp = self._post(lingkungan_t2.client)
        assert resp.status_code == 200
        assert resp.json()["source"] == "tier1"  # planner lama yang menjawab
        assert entri["status"] == "approved"     # tidak dihapus/di-stale-kan
        assert entri["times_used"] == 0          # tidak di-replay

    # ---------------- flag ON: router tier 1 ------------------------------
    def test_flag_on_router_tier1_reuse_compose_tanpa_planner(
            self, lingkungan_t2, monkeypatch):
        self._pasang_flag(lingkungan_t2, True)
        lingkungan_t2.core.seed_config_global()
        gen = FakeGenerator(hasil=lingkungan_t2.gen.hasil_tier1_dari_compose())
        self._pasang_generator(monkeypatch, lingkungan_t2, gen)

        # hitung pemanggilan compose_sql di namespace pipeline — reuse hasil
        # generator berarti compose TIDAK dijalankan lagi di pipeline
        compose_panggilan = []
        asli_compose = chat_pipeline.compose_sql

        def hitung_compose(plan, schema_config, now=None):
            compose_panggilan.append(plan)
            return asli_compose(plan, schema_config, now=now)

        monkeypatch.setattr(chat_pipeline, "compose_sql", hitung_compose)

        resp = self._post(lingkungan_t2.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "tier1" and data["confidence"] == "B"
        assert data["memory_id"] is not None
        # compose TIDAK dipanggil ulang di pipeline (sudah selesai di generator)
        assert compose_panggilan == []
        # planner lama TIDAK dipanggil (router satu panggilan LLM)
        assert lingkungan_t2.planner_catatan == []
        # memory tersimpan dengan plan hasil router (bukan plan planner)
        mem = lingkungan_t2.core.sql_memory[0]
        assert mem["sumber"] == "tier1"
        assert json.loads(mem["plan_json"])["tables"] == ["penjualan"]

    # ---------------- flag ON: jalur tier 2 -------------------------------
    def test_flag_on_tier2_sukses_response_memory_audit(
            self, lingkungan_t2, monkeypatch):
        self._pasang_flag(lingkungan_t2, True)
        lingkungan_t2.core.seed_config_global()
        gen = FakeGenerator(hasil={"tier": 2, "sql": SQL_TIER2_VALID,
                                   "verdict": {"ok": True}, "attempts": 2})
        self._pasang_generator(monkeypatch, lingkungan_t2, gen)

        resp = self._post(lingkungan_t2.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "tier2"
        assert data["confidence"] == "C"
        assert data["attempts"] == 2
        assert "SELECT" in data["sql"]
        # memory pending baru: sumber tier2, plan {"tier2": true}
        mem = lingkungan_t2.core.sql_memory
        assert len(mem) == 1
        assert mem[0]["status"] == "pending"
        assert mem[0]["sumber"] == "tier2"
        assert json.loads(mem[0]["plan_json"]) == {"tier2": True}
        assert data["memory_id"] == mem[0]["id"]
        # audit sukses membawa SQL tier2
        audit = lingkungan_t2.core.audit_logs
        assert len(audit) == 1 and audit[0]["status"] == "success"
        assert audit[0]["generated_sql"] == data["sql"]
        assert audit[0]["ai_json_filter"] is not None
        # verifier tetap jalan di pipeline (EXPLAIN pada koneksi tenant)
        assert any(c[0] == "fetch" and "EXPLAIN" in c[1]
                   for c in lingkungan_t2.conn.catatan)

    def test_flag_on_tier2_verifier_pipeline_menolak_422(
            self, lingkungan_t2, monkeypatch):
        # Generator "bocor" SQL berobjek asing (simulasi ketidaksepakatan
        # verifier) -> verify_and_execute di pipeline menolak -> 422;
        # SQL TIDAK dieksekusi dan TIDAK disimpan ke memory.
        self._pasang_flag(lingkungan_t2, True)
        lingkungan_t2.core.seed_config_global()
        gen = FakeGenerator(hasil={"tier": 2,
                                   "sql": "SELECT * FROM tabel_hantu LIMIT 3",
                                   "verdict": {"ok": True}, "attempts": 1})
        self._pasang_generator(monkeypatch, lingkungan_t2, gen)

        resp = self._post(lingkungan_t2.client)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["gate"] == "whitelist"
        assert "tabel_hantu" in detail["reason"]
        assert lingkungan_t2.core.sql_memory == []
        assert lingkungan_t2.core.audit_logs[0]["status"] == "rejected"

    def test_flag_on_tier2_gagal_fallback_tier1_sukses(
            self, lingkungan_t2, monkeypatch):
        self._pasang_flag(lingkungan_t2, True)
        lingkungan_t2.core.seed_config_global()
        gen = FakeGenerator(error=Tier2Error("Tier 2 gagal setelah 3 percobaan"
                                             ": verifier menolak"))
        self._pasang_generator(monkeypatch, lingkungan_t2, gen)

        resp = self._post(lingkungan_t2.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "tier1" and data["confidence"] == "B"
        # fallback berarti planner lama dipakai
        assert lingkungan_t2.planner_catatan == ["omzet bulan ini"]
        # memory tertulis dari jalur tier1 (bukan tier2)
        assert lingkungan_t2.core.sql_memory[0]["sumber"] == "tier1"
        assert lingkungan_t2.core.audit_logs[0]["status"] == "success"

    def test_flag_on_keduanya_gagal_502_pesan_gabungan(
            self, lingkungan_t2, monkeypatch):
        from app.services.query_planner import PlanningError
        self._pasang_flag(lingkungan_t2, True)
        lingkungan_t2.core.seed_config_global()
        gen = FakeGenerator(error=Tier2Error("Tier 2 gagal setelah 3 percobaan"
                                             ": JSON rusak"))
        self._pasang_generator(monkeypatch, lingkungan_t2, gen)

        async def plan_gagal(*a, **k):
            raise PlanningError("rencana dari LLM tidak valid setelah retry")

        from app.services import chat_pipeline
        monkeypatch.setattr(chat_pipeline, "plan_query", plan_gagal)

        resp = self._post(lingkungan_t2.client)
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert "Tier 2 gagal" in detail and "fallback Tier 1" in detail
        assert "rencana dari LLM tidak valid" in detail  # jujur dua-duanya
        assert lingkungan_t2.core.audit_logs[0]["status"] == "error"

    # ---------------- memory replay tier2 ---------------------------------
    def test_memory_tier2_tanpa_tanggal_replay_tanpa_generator(
            self, lingkungan_t2):
        entri = lingkungan_t2.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT COUNT(*) AS c FROM penjualan",
            plan_json=json.dumps({"tier2": True}), sumber="tier2")
        resp = self._post(lingkungan_t2.client, question="OMZET BULAN INI!!!")
        assert resp.status_code == 200
        data = resp.json()
        # replay normal seperti tier1: 0 LLM, level A
        assert data["source"] == "memory" and data["confidence"] == "A"
        # generator (dan planner) tidak dipanggil — gen spy bawaan melempar
        # AssertionError bila dipanggil, jadi lolos = bukti tidak dipanggil
        assert entri["times_used"] == 1
        assert any(c[0] == "fetch" and "EXPLAIN" in c[1]
                   for c in lingkungan_t2.conn.catatan)  # verify tetap jalan

    def test_memory_tier2_dengan_tanggal_miss_regenerate(
            self, lingkungan_t2, monkeypatch):
        self._pasang_flag(lingkungan_t2, True)
        lingkungan_t2.core.seed_config_global()
        entri = lingkungan_t2.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT COUNT(*) AS c FROM penjualan "
                "WHERE tanggal >= '2026-08-01'",
            plan_json=json.dumps({"tier2": True}), sumber="tier2")
        gen = FakeGenerator(hasil={"tier": 2, "sql": SQL_TIER2_VALID,
                                   "verdict": {"ok": True}, "attempts": 1})
        self._pasang_generator(monkeypatch, lingkungan_t2, gen)

        resp = self._post(lingkungan_t2.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "tier2"  # dijawab ulang, bukan replay basi
        assert len(gen.panggilan) == 1    # generator memang dipanggil
        # baris lama TIDAK dihapus, TIDAK di-stale-kan, tidak dihitung dipakai
        assert entri["status"] == "approved"
        assert entri["times_used"] == 0
        assert len(lingkungan_t2.core.sql_memory) == 2  # lama + baru

    # ---------------- integrasi generator ASLI di pipeline ----------------
    def test_integrasi_generator_asli_tier2_verify_dua_kali(
            self, lingkungan_t2, monkeypatch):
        # Tanpa fake generator: generate_sql asli + fake LLM. Verifier harus
        # berjalan DUA kali (di generator saat repair-loop, lalu di
        # verify_and_execute) — bukti defense-in-depth docs v2 §1.
        from app.services import chat_pipeline
        self._pasang_flag(lingkungan_t2, True)
        lingkungan_t2.core.seed_config_global()
        # pulihkan generator ASLI (fixture memasang spy yang melempar)
        import app.services.tier2_generator as t2mod
        monkeypatch.setattr(chat_pipeline, "generate_sql", t2mod.generate_sql)
        llm, _ = _fake_llm([_json_tier2(SQL_TIER2_VALID)])

        async def llm_wrapper(system, user, ai_config):
            return await llm(system, user, ai_config)

        # panggil service langsung agar llm_call_fn bisa di-inject
        resp = asyncio.run(proses_pertanyaan(
            lingkungan_t2.core, lingkungan_t2.tpm, dict(PAYLOAD_USER),
            "omzet bulan ini", "JKT_01", now=NOW_TETAP,
            llm_call_fn=llm_wrapper))
        assert resp["source"] == "tier2" and resp["confidence"] == "C"
        assert resp["attempts"] == 1
        explain = [c for c in lingkungan_t2.conn.catatan
                   if c[0] == "fetch" and "EXPLAIN" in c[1]]
        assert len(explain) == 2  # generator + pipeline (defense-in-depth)


def defaultdict_deque():
    from collections import defaultdict, deque
    return defaultdict(deque)


def require_user_role_override():
    from app.core.security import require_user_role
    return require_user_role


# ===========================================================================
# Migration 008 — idempotent (HANYA bila DB dev docker hidup)
# ===========================================================================
class TestMigrasi008:
    def test_init_db_dua_kali_kolom_chat_tier2_idempotent(self):
        """Jalankan init_db 2x lalu pastikan kolom chat_tier2 ada TEPAT 1.

        Bila DB dev tidak hidup, test di-skip (konvensi integration manual).
        """
        import os
        from dotenv import load_dotenv
        load_dotenv(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env"))

        import asyncpg
        try:
            from init_db import init_db
            asyncio.run(init_db())
            asyncio.run(init_db())  # ke-2 harus aman (idempotent)
        except Exception as e:  # koneksi gagal / docker mati -> skip
            pytest.skip(f"DB dev tidak hidup — migrasi 008 diuji manual: {e}")

        async def _cek_kolom():
            dsn = (
                f"postgresql://{os.getenv('CORE_DB_USER')}:"
                f"{os.getenv('CORE_DB_PASSWORD')}@{os.getenv('CORE_DB_HOST')}:"
                f"{os.getenv('CORE_DB_PORT')}/{os.getenv('CORE_DB_NAME')}")
            conn = await asyncpg.connect(dsn)
            try:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_name = 'tenants' "
                    "AND column_name = 'chat_tier2'")
            finally:
                await conn.close()

        assert asyncio.run(_cek_kolom()) == 1
