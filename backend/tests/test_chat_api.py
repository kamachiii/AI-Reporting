"""Test Chat API (F3) — endpoint /chat/query + /chat/history tanpa DB nyata
dan tanpa LLM nyata.

Strategi:
- `require_user_role` di-override lewat app.dependency_overrides (guard role
  diuji terpisah pada TestGuardUserRole dengan token JWT nyata).
- `get_core_pool` & `get_tenant_pool_manager` pada modul router di-patch ke
  fake (pool core in-memory + fake pool tenant).
- `plan_query` pada modul chat_pipeline di-patch (fake planner; planner sendiri
  diuji di test_query_planner.py) — EXPLAIN verifier tetap jalan lewat fake
  koneksi sehingga "verifier tetap jalan" bisa dibuktikan dari catatan fetch.
"""
import asyncio
import copy
import json
import time
from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt

try:
    from app.core.config import settings
    from app.core.security import encrypt_credential, require_user_role
    from app.services.chat_pipeline import (
        _siapkan_skema_efektif, normalisasi_pertanyaan, proses_pertanyaan)
    from app.services.knowledge_base import validate_kb
    from app.services.query_planner import build_user_prompt
    from app.services.sql_composer import compose_sql
    HAS_CHAT = True
except ImportError:
    HAS_CHAT = False

from conftest import SCHEMA_CONFIG_DEALER

PAYLOAD_USER = {"user_id": 7, "username": "user_jkt", "role": "user",
                "allowed_branches": ["JKT_01"]}

RENCANA = {
    "tables": ["penjualan"],
    "columns": [{"agg": "SUM", "column": "penjualan.harga_deal",
                 "alias": "omzet"}],
    "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},
}
NOW_TETAP = datetime(2026, 9, 1, 10, 0)


def _skema_besar(jumlah_pengisi: int = 200) -> dict:
    """Skema dealer + tabel pengisi sampai melewati ambang gagal-cepat (150)."""
    skema = copy.deepcopy(SCHEMA_CONFIG_DEALER)
    for i in range(jumlah_pengisi):
        skema["tables"][f"tabel_pengisi_{i}"] = {
            "columns": [{"name": "id", "type": "integer",
                         "nullable": True, "default": None}],
            "primary_key": ["id"], "foreign_keys": [], "sample_rows": [],
        }
    return skema


# ===========================================================================
# Fake infrastruktur
# ===========================================================================
class FakeTenantConn:
    """Koneksi tenant palsu — catat semua panggilan, EXPLAIN selalu murah."""

    def __init__(self, hasil=None, explain_error=None, kolom=("omzet",)):
        self.hasil = hasil or []
        self.explain_error = explain_error
        self.kolom = kolom
        self.catatan = []

    async def fetch(self, sql, *args):
        self.catatan.append(("fetch", sql))
        if self.explain_error is not None:
            raise self.explain_error
        plan = [{"Plan": {"Total Cost": 12.0, "Plan Rows": 3}}]
        return [(json.dumps(plan),)]

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

        class _Stmt:
            def get_attributes(self):
                class _A:
                    def __init__(self, name):
                        self.name = name
                return [_A(k) for k in self._kolom]
        stmt = _Stmt()
        stmt._kolom = self.kolom
        return stmt

    def cursor(self, sql, *args):
        self.catatan.append(("cursor", sql, args))
        fake = self

        class _AwaitableCursor:
            def __await__(self):
                if False:
                    yield
                return self

            async def fetch(self, n):
                return fake.hasil[:n]
        return _AwaitableCursor()


class FakeTenantPool:
    def __init__(self, conn):
        self.conn = conn

    async def acquire(self):
        return self.conn

    async def release(self, conn):
        pass


class FakeTenantPoolManager:
    def __init__(self, conn):
        self.conn = conn
        self.dipanggil = 0

    async def get_pool(self, db_conn_row):
        self.dipanggil += 1
        return FakeTenantPool(self.conn)


class FakeCorePool:
    """Pool DB core in-memory: tabel yang dipakai chat_pipeline + router."""

    def __init__(self):
        self.tenant = None          # baris join tenants+db_connections
        self.ai_configs = []
        self.sql_memory = []
        self.conversations = []
        self.messages = []
        self.audit_logs = []
        self.next_id = 100

    # -- tenants + db_connections -----------------------------------------
    def seed_tenant(self):
        self.tenant = {
            "tenant_id": 3, "branch_code": "JKT_01",
            "schema_config_json": json.dumps(SCHEMA_CONFIG_DEALER),
            "knowledge_base": None, "tenant_aktif": True,
            "db_connection_id": 9, "db_host": "localhost", "db_port": 5433,
            "db_name": "dealer_dummy", "db_username": "u_ro",
            "db_password": encrypt_credential("p"), "koneksi_aktif": True,
        }

    # -- asyncpg-like API ---------------------------------------------------
    async def fetchrow(self, sql, *args):
        if "FROM tenants t" in sql:
            return dict(self.tenant) if (
                self.tenant and self.tenant["branch_code"] == args[0]) else None
        if "FROM ai_configs" in sql:
            scope, target = args
            for row in self.ai_configs:
                if row["scope"] == scope and row["target_id"] == target:
                    return dict(row)
            return None
        if "FROM sql_memory" in sql:
            if "WHERE id = $1 AND tenant_id = $2" in sql:
                # F4 ubah_status_memory: cari entri milik satu tenant
                memory_id, tenant_id = args
                for row in self.sql_memory:
                    if row["id"] == memory_id and row["tenant_id"] == tenant_id:
                        return row
                return None
            if "AND sql = $3" in sql:
                tenant_id, q_norm, sql_tersimpan = args
                for row in self.sql_memory:
                    if (row["tenant_id"] == tenant_id
                            and row["pertanyaan_ternormalisasi"] == q_norm
                            and row["sql"] == sql_tersimpan):
                        return row
                return None
            tenant_id, q_norm = args
            kandidat = [r for r in self.sql_memory
                        if r["tenant_id"] == tenant_id
                        and r["pertanyaan_ternormalisasi"] == q_norm
                        and r["status"] == "approved"]
            if not kandidat:
                return None
            return sorted(kandidat, key=lambda r: (-r["times_used"], r["id"]))[0]
        raise AssertionError(f"fetchrow tak dikenal: {sql[:90]}")

    async def fetchval(self, sql, *args):
        if "FROM tenants WHERE branch_code" in sql:
            # F4 ubah_status_memory: pemetaan branch -> tenant_id
            return self.tenant["tenant_id"] if (
                self.tenant and self.tenant["branch_code"] == args[0]) else None
        if "SELECT id FROM conversations" in sql:
            user_id, branch_code = args
            cocok = [c for c in self.conversations
                     if c["user_id"] == user_id and c["branch_code"] == branch_code]
            return cocok[-1]["id"] if cocok else None
        if "INSERT INTO conversations" in sql:
            self.next_id += 1
            self.conversations.append({
                "id": self.next_id, "user_id": args[0],
                "branch_code": args[1], "title": args[2]})
            return self.next_id
        if "INSERT INTO sql_memory" in sql:
            tenant_id, q_norm, sql_txt, plan_json, sumber, fingerprint = args
            self.next_id += 1
            self.sql_memory.append({
                "id": self.next_id, "tenant_id": tenant_id,
                "pertanyaan_ternormalisasi": q_norm, "sql": sql_txt,
                "plan_json": plan_json, "status": "pending", "sumber": sumber,
                "times_used": 0, "last_used": None,
                "fingerprint_tabel": fingerprint})
            return self.next_id
        raise AssertionError(f"fetchval tak dikenal: {sql[:90]}")

    async def execute(self, sql, *args):
        if "UPDATE sql_memory" in sql:
            mid = args[-1]
            for row in self.sql_memory:
                if row["id"] == mid:
                    if "times_used = times_used + 1" in sql:
                        row["times_used"] += 1
                    elif "status = 'stale'" in sql:
                        row["status"] = "stale"
                    elif "SET status = $1" in sql:
                        # F4 ubah_status_memory: pending -> approved/rejected
                        row["status"] = args[0]
                    elif "SET plan_json" in sql:
                        row["plan_json"], row["sumber"], row["fingerprint_tabel"] = args[0], args[1], args[2]
            return "OK"
        if "INSERT INTO audit_logs" in sql:
            self.audit_logs.append({
                "user_id": args[0], "branch_code": args[1],
                "prompt_text": args[2], "ai_json_filter": args[3],
                "generated_sql": args[4], "execution_time_ms": args[5],
                "status": args[6], "error_message": args[7]})
            return "OK"
        if "INSERT INTO messages" in sql:
            self.next_id += 1
            self.messages.append({
                "id": self.next_id, "conversation_id": args[0],
                "role": args[1], "content": args[2],
                "created_at": datetime(2026, 9, 1, 10, 0)})
            return "OK"
        raise AssertionError(f"execute tak dikenal: {sql[:90]}")

    async def fetch(self, sql, *args):
        if "FROM messages" in sql:
            conv_id = args[0]
            rows = [dict(m) for m in self.messages
                    if m["conversation_id"] == conv_id]
            return sorted(rows, key=lambda m: -m["id"])[:50]
        raise AssertionError(f"fetch tak dikenal: {sql[:90]}")

    def seed_memory(self, *, q_norm, sql, plan_json=None, status="approved",
                    times_used=0, tenant_id=3):
        self.next_id += 1
        self.sql_memory.append({
            "id": self.next_id, "tenant_id": tenant_id,
            "pertanyaan_ternormalisasi": q_norm, "sql": sql,
            "plan_json": plan_json, "status": status, "sumber": "tier1",
            "times_used": times_used, "last_used": None,
            "fingerprint_tabel": "penjualan"})
        return self.sql_memory[-1]

    def seed_config_global(self):
        self.ai_configs.append({
            "id": 5, "scope": "global", "target_id": "", "provider": "openai",
            "model": "gpt-test", "api_key": encrypt_credential("sk-test"),
            "temperature": 0.1, "api_type": "openai", "base_url": ""})


# ===========================================================================
# Fixture lingkungan
# ===========================================================================
@pytest.fixture
def lingkungan(monkeypatch):
    from app.main import app
    from app.routers import chat as chat_router
    from app.services import chat_pipeline

    fake_core = FakeCorePool()
    fake_core.seed_tenant()
    conn = FakeTenantConn(hasil=[(Decimal("850000000"),)])
    fake_tpm = FakeTenantPoolManager(conn)
    planner_catatan = []

    async def _pool():
        return fake_core

    async def fake_plan_query(question, schema_config, kb, ai_config,
                              llm_call_fn=None):
        planner_catatan.append({"question": question, "schema": schema_config,
                                "kb": kb, "ai_config": ai_config})
        return copy.deepcopy(RENCANA)

    monkeypatch.setattr(chat_router, "get_core_pool", _pool)
    monkeypatch.setattr(chat_router, "get_tenant_pool_manager",
                        lambda: fake_tpm)
    monkeypatch.setattr(chat_router, "_chat_calls", defaultdict(deque))
    monkeypatch.setattr(chat_pipeline, "plan_query", fake_plan_query)

    app.dependency_overrides[require_user_role] = lambda: dict(PAYLOAD_USER)
    client = TestClient(app)

    class Lingkungan:
        pass
    env = Lingkungan()
    env.client = client
    env.core = fake_core
    env.conn = conn
    env.tpm = fake_tpm
    env.planner_catatan = planner_catatan
    env.chat_router = chat_router
    yield env
    app.dependency_overrides.clear()


def _post(client, question="omzet bulan ini", branch="JKT_01"):
    return client.post("/chat/query", json={"question": question,
                                            "branch_code": branch})


@pytest.mark.skipif(not HAS_CHAT, reason="chat pipeline belum ada")
class TestChatQueryTier1:
    def test_sukses_tier1(self, lingkungan):
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "tier1"
        assert data["confidence"] == "B"
        assert "SELECT" in data["sql"] and "LIMIT" in data["sql"]
        assert data["sql"] == "$n" or "$1" in data["sql"] or "NULL" not in data["sql"]
        assert data["columns"] == ["omzet"]
        assert data["rows"] == [[850000000.0]]  # Decimal -> float
        assert data["row_count"] == 1 and data["truncated"] is False
        assert data["duration_ms"] >= 0
        # gerbang #5 jalan (EXPLAIN) lalu gerbang #6 (READ ONLY + timeout)
        assert any(c[0] == "fetch" and "EXPLAIN" in c[1] for c in lingkungan.conn.catatan)
        assert ("transaction", {"readonly": True}) in lingkungan.conn.catatan
        assert ("execute", "SET LOCAL statement_timeout = '10s'" ) in lingkungan.conn.catatan
        # planner menerima ai_config dgn api_key sudah didekripsi
        assert lingkungan.planner_catatan[0]["ai_config"]["api_key"] == "sk-test"

    def test_sukses_menyimpan_memory_pending_dan_audit(self, lingkungan):
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        mem = lingkungan.core.sql_memory
        assert len(mem) == 1
        assert mem[0]["status"] == "pending"
        assert mem[0]["sumber"] == "tier1"
        assert mem[0]["fingerprint_tabel"] == "penjualan"
        assert json.loads(mem[0]["plan_json"])["tables"] == ["penjualan"]
        # F4: id baris pending yang baru dibuat ikut dalam response
        assert resp.json()["memory_id"] == mem[0]["id"]
        # percakapan: 2 pesan (user + assistant)
        roles = [m["role"] for m in lingkungan.core.messages]
        assert roles == ["user", "assistant"]
        # audit sukses
        audit = lingkungan.core.audit_logs
        assert len(audit) == 1
        assert audit[0]["status"] == "success"
        assert audit[0]["generated_sql"] == resp.json()["sql"]
        assert audit[0]["user_id"] == 7 and audit[0]["branch_code"] == "JKT_01"

    def test_tanpa_config_503_teraudit(self, lingkungan):
        resp = _post(lingkungan.client)  # tanpa ai_configs, tanpa memory
        assert resp.status_code == 503
        assert "belum dikonfigurasi" in resp.json()["detail"]
        audit = lingkungan.core.audit_logs
        assert len(audit) == 1
        assert audit[0]["status"] == "error"
        assert "AI belum dikonfigurasi" in audit[0]["error_message"]

    def test_planner_plan_tak_valid_compose_502(self, lingkungan):
        # plan lolos tapi merujuk tabel tak berhubungan FK -> compose gagal
        from app.services import chat_pipeline
        import app.routers.chat as cr
        # patch plan_query agar menghasilkan rencana tabel asing
        async def plan_asing(question, schema, kb, ai_config, llm_call_fn=None):
            return {"tables": ["kendaraan"], "columns": ["penjualan.tanggal"]}
        cr._chat_calls  # pastikan modul termuat
        monkey_plan = plan_asing
        # monkeypatch manual karena fixture sudah memasang fake lain
        old = chat_pipeline.plan_query
        chat_pipeline.plan_query = monkey_plan
        lingkungan.core.seed_config_global()
        try:
            resp = _post(lingkungan.client)
            assert resp.status_code == 502
            assert "compose" in resp.json()["detail"].lower()
            assert lingkungan.core.audit_logs[0]["status"] == "error"
        finally:
            chat_pipeline.plan_query = old

    def test_verifier_tolak_explain_422_teraudit(self, lingkungan):
        # EXPLAIN gagal (fail-closed gerbang #5) -> 422 gate explain + audit
        lingkungan.core.seed_config_global()
        lingkungan.conn.explain_error = RuntimeError("column tidak ada")
        resp = _post(lingkungan.client)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["gate"] == "explain"
        assert "EXPLAIN gagal" in detail["reason"]
        assert lingkungan.core.audit_logs[0]["status"] == "rejected"
        # SQL tidak tersimpan ke memory bila verifier menolak
        assert lingkungan.core.sql_memory == []

    def test_branch_luar_403(self, lingkungan):
        from app.core.security import require_user_role
        from app.main import app
        payload = {**PAYLOAD_USER, "allowed_branches": ["SBY_02"]}
        app.dependency_overrides[require_user_role] = lambda: payload
        resp = _post(lingkungan.client, branch="JKT_01")
        assert resp.status_code == 403
        assert "bukan penugasan" in resp.json()["detail"]

    def test_tenant_tak_ada_409(self, lingkungan):
        from app.core.security import require_user_role
        from app.main import app
        payload = {**PAYLOAD_USER, "allowed_branches": ["JKT_01", "XXX_99"]}
        app.dependency_overrides[require_user_role] = lambda: payload
        resp = _post(lingkungan.client, branch="XXX_99")
        assert resp.status_code == 409
        assert "belum terhubung" in resp.json()["detail"]


@pytest.mark.skipif(not HAS_CHAT, reason="chat pipeline belum ada")
class TestChatQueryMemory:
    def _seed(self, lingkungan, now=NOW_TETAP):
        composed = compose_sql(RENCANA, SCHEMA_CONFIG_DEALER, now=now)
        lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql=composed["sql"], plan_json=json.dumps(RENCANA))
        return composed

    def test_memory_hit_tanpa_llm(self, lingkungan):
        self._seed(lingkungan)
        resp = _post(lingkungan.client, question="OMZET BULAN INI!!!")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "memory"
        assert data["confidence"] == "A"
        assert "$1" in data["sql"] or "$2" in data["sql"]
        # F4: replay tidak membuat entri pending baru -> memory_id null
        assert data["memory_id"] is None
        # VERIFIER TETAP JALAN pada SQL tersimpan (bukti: EXPLAIN dipanggil)
        assert any(c[0] == "fetch" and "EXPLAIN" in c[1]
                   for c in lingkungan.conn.catatan)
        # tidak ada resolve_ai_config / planner (ai_configs kosong pun lolos)
        assert lingkungan.planner_catatan == []
        # times_used bertambah
        assert lingkungan.core.sql_memory[0]["times_used"] == 1

    def test_memory_hit_params_dihitung_ulang_dari_now(self, lingkungan):
        # entri disetujui ~3 bulan lalu; replay hari ini -> jendela waktu baru
        from datetime import date, timedelta
        tiga_bulan_lalu = date.today() - timedelta(days=95)
        composed_lama = self._seed(
            lingkungan, now=datetime(tiga_bulan_lalu.year,
                                     tiga_bulan_lalu.month,
                                     tiga_bulan_lalu.day, 9, 0))
        resp = _post(lingkungan.client, question="omzet bulan ini")
        assert resp.status_code == 200
        data = resp.json()
        # SQL tetap byte-identik (deterministik terhadap rencana) ...
        assert data["sql"] == composed_lama["sql"]
        # ... tetapi params dihitung ULANG: batas bawah = awal bulan berjalan
        awal_bulan_ini = date.today().replace(day=1)
        assert data["params"][0] == str(awal_bulan_ini)
        assert data["params"] != [str(p) for p in composed_lama["params"]]

    def test_memory_hit_komposisi_berubah_tandai_stale(self, lingkungan):
        composed = compose_sql(RENCANA, SCHEMA_CONFIG_DEALER, now=NOW_TETAP)
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql=composed["sql"].replace("LIMIT 200", "LIMIT 200 ") + " ",
            plan_json=json.dumps(RENCANA))
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        # SQL tersimpan tidak cocok komposisi ulang -> stale, jalur tier1
        assert resp.status_code == 200
        assert resp.json()["source"] == "tier1"
        assert entri["status"] == "stale"

    def test_memory_verifier_tolak_422_stale_audit(self, lingkungan):
        # entri approved berisi tabel yang tidak lagi ada di whitelist
        lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT * FROM tabel_hantu LIMIT 10", plan_json=None)
        entri = lingkungan.core.sql_memory[0]
        resp = _post(lingkungan.client)
        assert resp.status_code == 422
        assert resp.json()["detail"]["gate"] == "whitelist"
        assert entri["status"] == "stale"  # invalidasi otomatis
        assert lingkungan.core.audit_logs[0]["status"] == "rejected"

    def test_memory_hit_dengan_now_tetap_service_level(self, lingkungan):
        # uji service langsung: now di-inject -> params deterministik
        composed = self._seed(lingkungan, now=NOW_TETAP)
        conn_baru = FakeTenantConn(hasil=[(1.0,)])
        lingkungan.tpm.conn = conn_baru
        from app.services import chat_pipeline as cp
        resp = asyncio.run(proses_pertanyaan(
            lingkungan.core, lingkungan.tpm, PAYLOAD_USER,
            "omzet bulan ini", "JKT_01", now=NOW_TETAP))
        assert resp["source"] == "memory"
        assert [str(p) for p in resp["params"]] == [
            str(p) for p in composed["params"]]


@pytest.mark.skipif(not HAS_CHAT, reason="chat pipeline belum ada")
class TestSkemaEfektifTenant:
    """Allowlist `tabel_diizinkan` (KB) -> skema efektif untuk SEMUA tahap
    downstream (planner, composer, verifier); tenant skema raksasa tanpa
    allowlist gagal cepat 422 (gate "skema")."""

    def test_skema_besar_tanpa_allowlist_gagal_cepat_422(self, lingkungan):
        # 205 tabel (> ambang 150) tanpa tabel_diizinkan -> tolak SEBELUM
        # planner LLM / pool tenant disentuh (gagal cepat, hemat token)
        lingkungan.core.tenant["schema_config_json"] = json.dumps(
            _skema_besar(200))
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["gate"] == "skema"
        assert "terlalu besar (205 tabel)" in detail["reason"]
        assert "tabel_diizinkan" in detail["reason"]
        assert lingkungan.planner_catatan == []
        assert lingkungan.tpm.dipanggil == 0
        # ter-audit sebagai rejected dengan pesan yang sama
        assert lingkungan.core.audit_logs[0]["status"] == "rejected"
        assert "terlalu besar" in lingkungan.core.audit_logs[0]["error_message"]

    def test_allowlist_3_tabel_planner_hanya_lihat_skema_terfilter(
            self, lingkungan):
        lingkungan.core.tenant["schema_config_json"] = json.dumps(
            _skema_besar(200))
        lingkungan.core.tenant["knowledge_base"] = json.dumps(
            {"tabel_diizinkan": ["penjualan", "kendaraan", "pelanggan"]})
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        assert resp.json()["source"] == "tier1"
        # planner menerima skema terfilter: HANYA 3 tabel allowlist (bukan 205)
        skema = lingkungan.planner_catatan[0]["schema"]
        assert set(skema["tables"]) == {"penjualan", "kendaraan", "pelanggan"}
        # struktur kolom tabel yang lolos dipertahankan apa adanya
        kolom = {c["name"] for c in skema["tables"]["penjualan"]["columns"]}
        assert {"id", "tanggal", "harga_deal"} <= kolom
        # audit mencatat jumlah tabel efektif yang dipakai
        catatan = json.loads(lingkungan.core.audit_logs[0]["ai_json_filter"])
        assert catatan["tables_effective"] == 3
        assert catatan["plan"]["tables"] == ["penjualan"]

    def test_verify_hanya_menerima_tabel_allowlist(self, lingkungan):
        # SQL memory approved merujuk tabel skema penuh di LUAR allowlist ->
        # whitelist verifier otomatis menyempit (tanpa perubahan verifier) ->
        # verdict tolak -> 422 + invalidasi stale
        lingkungan.core.tenant["knowledge_base"] = json.dumps(
            {"tabel_diizinkan": ["penjualan", "kendaraan", "pelanggan"]})
        lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT COUNT(*) FROM service_records LIMIT 10", plan_json=None)
        entri = lingkungan.core.sql_memory[0]
        resp = _post(lingkungan.client)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["gate"] == "whitelist"
        assert "service_records" in detail["reason"]
        assert entri["status"] == "stale"
        assert lingkungan.core.audit_logs[0]["status"] == "rejected"

    def test_tabel_dilarang_menang_atas_diizinkan(self, lingkungan):
        # bentrok: penjualan ada di dua daftar -> tetap dipotong (dilarang
        # menang atas diizinkan); planner bekerja pada sisa skema efektif
        lingkungan.core.tenant["schema_config_json"] = json.dumps(
            _skema_besar(200))
        lingkungan.core.tenant["knowledge_base"] = json.dumps({
            "tabel_diizinkan": ["penjualan", "kendaraan", "pelanggan"],
            "tabel_dilarang": ["penjualan"]})
        lingkungan.core.seed_config_global()
        from app.services import chat_pipeline
        catatan_lokal = []

        async def plan_kendaraan(question, schema_config, kb, ai_config,
                                 llm_call_fn=None):
            catatan_lokal.append(schema_config)
            return {"tables": ["kendaraan"], "columns": ["kendaraan.merek"]}

        old = chat_pipeline.plan_query
        chat_pipeline.plan_query = plan_kendaraan
        try:
            resp = _post(lingkungan.client)
        finally:
            chat_pipeline.plan_query = old
        assert resp.status_code == 200
        assert set(catatan_lokal[0]["tables"]) == {"kendaraan", "pelanggan"}
        catatan = json.loads(lingkungan.core.audit_logs[0]["ai_json_filter"])
        assert catatan["tables_effective"] == 2

    def test_kolom_dikecualikan_hilang_dari_skema_efektif(self, lingkungan):
        # KB `kolom_dikecualikan` -> kolom dibuang dari skema efektif yang
        # dilihat planner (tabel & kolom lain tetap utuh)
        lingkungan.core.tenant["knowledge_base"] = json.dumps(
            {"kolom_dikecualikan": ["penjualan.catatan"]})
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        skema = lingkungan.planner_catatan[0]["schema"]
        kolom = {c["name"] for c in skema["tables"]["penjualan"]["columns"]}
        assert "catatan" not in kolom          # yang dikecualikan hilang
        assert {"id", "tanggal", "harga_deal"} <= kolom  # sisanya utuh
        catatan = json.loads(lingkungan.core.audit_logs[0]["ai_json_filter"])
        assert catatan["tables_effective"] == 5  # tabel tidak ikut terbuang

    def test_kolom_dikecualikan_ditolak_verifier(self, lingkungan):
        # SQL memory approved memakai kolom yang sudah dikecualikan -> skema
        # efektif yang sama dipakai verifier -> whitelist menolak (tanpa
        # perubahan verifier) -> 422 + invalidasi stale
        lingkungan.core.tenant["knowledge_base"] = json.dumps(
            {"kolom_dikecualikan": ["penjualan.nama_sales"]})
        lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT nama_sales FROM penjualan LIMIT 10", plan_json=None)
        entri = lingkungan.core.sql_memory[0]
        resp = _post(lingkungan.client)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["gate"] == "whitelist"
        assert "nama_sales" in detail["reason"]
        assert entri["status"] == "stale"
        assert lingkungan.core.audit_logs[0]["status"] == "rejected"

    def test_allowlist_nama_tak_ada_diabaikan_dengan_catatan(self, lingkungan):
        lingkungan.core.tenant["knowledge_base"] = json.dumps(
            {"tabel_diizinkan": ["penjualan", "tabel_hantu"]})
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        assert set(lingkungan.planner_catatan[0]["schema"]["tables"]) == {
            "penjualan"}
        catatan = json.loads(lingkungan.core.audit_logs[0]["ai_json_filter"])
        assert catatan["tables_effective"] == 1
        assert catatan["tables_ignored"] == ["tabel_hantu"]

    def test_allowlist_tak_cocok_semua_gagal_cepat_422(self, lingkungan):
        lingkungan.core.tenant["knowledge_base"] = json.dumps(
            {"tabel_diizinkan": ["tabel_hantu"]})
        resp = _post(lingkungan.client)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["gate"] == "skema"
        assert "tabel_diizinkan" in detail["reason"]
        assert lingkungan.planner_catatan == []


# Nama & tipe realistis khas DB tenant (varchar dominan) — dipakai membangun
# skema besar untuk benchmark ukuran prompt; distribusi tipe dibobot agar
# mendekati skema nyata (TST_01: 763 kolom).
_NAMA_KOLOM_DASAR = [
    "id", "kode", "nama", "status", "tanggal", "jumlah", "harga", "total",
    "keterangan", "catatan", "no_dokumen", "tipe", "kategori", "kuantitas",
    "diskon", "pajak", "subtotal", "berat", "volume", "serial",
    "no_telepon", "email", "alamat", "kota", "kode_pos", "tanggal_mulai",
    "tanggal_selesai", "updated_by", "created_at", "is_aktif",
]
_TIPE_TERBOBOT = (
    ["character varying"] * 45 + ["integer"] * 15 + ["bigint"] * 10
    + ["date"] * 8 + ["timestamp without time zone"] * 10 + ["text"] * 7
    + ["numeric"] * 3 + ["boolean"] * 2)
_NAMA_TABEL_DEALER = [
    "penjualan", "kendaraan", "pelanggan", "detail_penjualan",
    "service_records", "pembelian", "supplier", "stok_sparepart",
    "karyawan", "cicilan", "trade_in",
]


def _skema_11x70() -> dict:
    """Skema 11 tabel × 70 kolom (770 total) dengan nama/tipe realistis."""
    skema = {"introspected_at": "2026-09-01T00:00:00+00:00", "tables": {}}
    for t, nama_tabel in enumerate(_NAMA_TABEL_DEALER):
        kolom = []
        for i in range(70):
            dasar = _NAMA_KOLOM_DASAR[i % len(_NAMA_KOLOM_DASAR)]
            nama = dasar if i < len(_NAMA_KOLOM_DASAR) else f"{dasar}_{i}"
            kolom.append({"name": nama, "type": _TIPE_TERBOBOT[i % len(_TIPE_TERBOBOT)],
                          "nullable": True, "default": None})
        skema["tables"][nama_tabel] = {
            "columns": kolom, "primary_key": ["id"], "foreign_keys": [],
            "sample_rows": [],
        }
    return skema


def _300_kolom_dikecualikan() -> list[str]:
    """300 entri 'tabel.kolom' valid dari skema 11×70 (baris-mayor)."""
    entri = []
    for t, nama_tabel in enumerate(_NAMA_TABEL_DEALER):
        for i in range(70):
            if len(entri) >= 300:
                break
            dasar = _NAMA_KOLOM_DASAR[i % len(_NAMA_KOLOM_DASAR)]
            nama = dasar if i < len(_NAMA_KOLOM_DASAR) else f"{dasar}_{i}"
            entri.append(f"{nama_tabel}.{nama}")
    return entri


@pytest.mark.skipif(not HAS_CHAT, reason="chat pipeline belum ada")
class TestUkuranPromptPlanner:
    """Bukti optimasi TPM 8000: prompt planner untuk skema besar (11 tabel ×
    70 kolom, 300 kolom dikecualikan) harus < 12.000 char (~3.000 token)."""

    def test_prompt_kurang_dari_12ribu_char(self):
        skema = _skema_11x70()
        kb, errors = validate_kb(
            {"kolom_dikecualikan": _300_kolom_dikecualikan()})
        assert errors == []
        # alur nyata: KB -> skema efektif (chat_pipeline) -> prompt (planner)
        skema_efektif, _ = _siapkan_skema_efektif(
            skema, [], [], kb["kolom_dikecualikan"])
        prompt = build_user_prompt("omzet bulan ini berapa?", skema_efektif, kb)
        assert len(prompt) < 12_000, \
            f"len(user_prompt)={len(prompt)} char — melebihi batas 12.000"
        # semua kolom yang lolos masih tampil (planner butuh memilih)
        assert "harga" in prompt and "no_dokumen" in prompt

    def test_skema_efektif_benar_470_kolom(self):
        skema = _skema_11x70()
        kb, _ = validate_kb(
            {"kolom_dikecualikan": _300_kolom_dikecualikan()})
        skema_efektif, _ = _siapkan_skema_efektif(
            skema, [], [], kb["kolom_dikecualikan"])
        total = sum(len(t["columns"])
                    for t in skema_efektif["tables"].values())
        assert total == 770 - 300 == 470


@pytest.mark.skipif(not HAS_CHAT, reason="chat pipeline belum ada")
class TestKeputusanMemory:
    """F4 — endpoint /chat/confirm-memory + /chat/reject-memory."""

    def _keputusan(self, client, aksi, memory_id, branch="JKT_01"):
        return client.post(f"/chat/{aksi}-memory",
                           json={"branch_code": branch,
                                 "memory_id": memory_id})

    def test_confirm_id_dari_response_query(self, lingkungan):
        # Alur UI nyata: /chat/query tier1 -> memory_id -> tombol "benar"
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        memory_id = resp.json()["memory_id"]
        assert isinstance(memory_id, int)

        resp2 = self._keputusan(lingkungan.client, "confirm", memory_id)
        assert resp2.status_code == 200
        assert resp2.json() == {"ok": True, "status": "approved"}
        assert lingkungan.core.sql_memory[0]["status"] == "approved"
        # audit: query sukses + confirm sukses
        statuses = [a["status"] for a in lingkungan.core.audit_logs]
        assert statuses == ["success", "success"]
        assert "confirm-memory" in lingkungan.core.audit_logs[1]["prompt_text"]
        # SQL tersimpan tidak berubah oleh confirm (hanya status dinaikkan)
        assert lingkungan.core.audit_logs[1]["generated_sql"] == \
            lingkungan.core.audit_logs[0]["generated_sql"]

    def test_confirm_pending_langsung_sukses(self, lingkungan):
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT 1", status="pending")
        resp = self._keputusan(lingkungan.client, "confirm", entri["id"])
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "status": "approved"}
        assert entri["status"] == "approved"
        assert lingkungan.core.audit_logs[0]["status"] == "success"

    def test_reject_pending_sukses(self, lingkungan):
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT 1", status="pending")
        resp = self._keputusan(lingkungan.client, "reject", entri["id"])
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "status": "rejected"}
        assert entri["status"] == "rejected"
        assert lingkungan.core.audit_logs[0]["status"] == "success"

    def test_confirm_approved_noop_sukses(self, lingkungan):
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT 1", status="approved", times_used=2)
        resp = self._keputusan(lingkungan.client, "confirm", entri["id"])
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "status": "approved"}
        # no-op: status & metrik tidak berubah, tidak ada baris baru
        assert entri["status"] == "approved"
        assert entri["times_used"] == 2
        assert len(lingkungan.core.sql_memory) == 1

    def test_reject_rejected_noop_sukses(self, lingkungan):
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT 1", status="rejected")
        resp = self._keputusan(lingkungan.client, "reject", entri["id"])
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "status": "rejected"}
        assert entri["status"] == "rejected"

    def test_reject_approved_ditolak_409(self, lingkungan):
        # Status tidak pernah diturunkan: approved TIDAK boleh jadi rejected
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT 1", status="approved")
        resp = self._keputusan(lingkungan.client, "reject", entri["id"])
        assert resp.status_code == 409
        assert "approved" in resp.json()["detail"]
        assert entri["status"] == "approved"  # tidak berubah
        # percobaan yang ditolak tetap ter-audit sebagai error
        assert lingkungan.core.audit_logs[0]["status"] == "error"

    def test_confirm_rejected_ditolak_409(self, lingkungan):
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT 1", status="rejected")
        resp = self._keputusan(lingkungan.client, "confirm", entri["id"])
        assert resp.status_code == 409
        assert "ditandai salah" in resp.json()["detail"]
        assert entri["status"] == "rejected"
        assert lingkungan.core.audit_logs[0]["status"] == "error"

    def test_confirm_stale_ditolak_409(self, lingkungan):
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT 1", status="stale")
        resp = self._keputusan(lingkungan.client, "confirm", entri["id"])
        assert resp.status_code == 409
        assert "stale" in resp.json()["detail"]
        assert entri["status"] == "stale"

    def test_bukan_pemilik_tidak_ada_404(self, lingkungan):
        # memory_id yang tidak ada -> 404 (bukan 400/500)
        resp = self._keputusan(lingkungan.client, "confirm", 9999)
        assert resp.status_code == 404
        assert "tidak ditemukan" in resp.json()["detail"]

    def test_cross_tenant_404(self, lingkungan):
        # entri milik tenant lain (999) tidak terlihat dari cabang JKT_01
        entri = lingkungan.core.seed_memory(
            q_norm=normalisasi_pertanyaan("omzet bulan ini"),
            sql="SELECT 1", status="pending", tenant_id=999)
        resp = self._keputusan(lingkungan.client, "confirm", entri["id"])
        assert resp.status_code == 404
        assert entri["status"] == "pending"  # tidak tersentuh

    def test_branch_bukan_penugasan_403(self, lingkungan):
        from app.core.security import require_user_role
        from app.main import app
        payload = {**PAYLOAD_USER, "allowed_branches": ["SBY_02"]}
        app.dependency_overrides[require_user_role] = lambda: payload
        resp = self._keputusan(lingkungan.client, "confirm", 1,
                               branch="JKT_01")
        assert resp.status_code == 403
        assert "bukan penugasan" in resp.json()["detail"]

    def test_tenant_tidak_ada_409(self, lingkungan):
        lingkungan.core.tenant = None  # cabang belum terhubung tenant
        resp = self._keputusan(lingkungan.client, "confirm", 1)
        assert resp.status_code == 409
        assert "belum terhubung" in resp.json()["detail"]


@pytest.mark.skipif(not HAS_CHAT, reason="chat pipeline belum ada")
class TestRateLimitDanHistory:
    def test_rate_limit_429(self, lingkungan):
        for _ in range(10):
            lingkungan.chat_router._chat_calls[7].append(time.monotonic())
        resp = _post(lingkungan.client)
        assert resp.status_code == 429
        assert "Terlalu banyak" in resp.json()["detail"]

    def test_rate_limit_reset_antar_test(self, lingkungan):
        # fixture memasang dict baru — dict kosong => lolos
        resp = _post(lingkungan.client)
        assert resp.status_code != 429

    def test_history_50_terakhir_urut_lama_ke_baru(self, lingkungan):
        lingkungan.core.next_id += 1
        conv = {"id": lingkungan.core.next_id, "user_id": 7,
                "branch_code": "JKT_01", "title": "t"}
        lingkungan.core.conversations.append(conv)
        for i in range(60):
            lingkungan.core.next_id += 1
            lingkungan.core.messages.append({
                "id": lingkungan.core.next_id,
                "conversation_id": conv["id"], "role": "user",
                "content": f"pesan-{i}",
                "created_at": datetime(2026, 9, 1, 10, i)})
        resp = lingkungan.client.get("/chat/history", params={"branch_code": "JKT_01"})
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 50
        # 60 pesan -> 50 terakhir = pesan-10 .. pesan-59, urut lama->baru
        assert messages[0]["content"] == "pesan-10"
        assert messages[-1]["content"] == "pesan-59"

    def test_history_kosong(self, lingkungan):
        resp = lingkungan.client.get("/chat/history", params={"branch_code": "JKT_01"})
        assert resp.status_code == 200
        assert resp.json() == {"conversation_id": None, "messages": []}

    def test_history_branch_luar_403(self, lingkungan):
        resp = lingkungan.client.get("/chat/history", params={"branch_code": "SBY_02"})
        assert resp.status_code == 403


@pytest.mark.skipif(not HAS_CHAT, reason="chat pipeline belum ada")
class TestGuardUserRole:
    """Guard langsung (tanpa override): admin DITOLAK, user lolos."""

    def _creds(self, role):
        token = jwt.encode(
            {"sub": "1", "user_id": 1, "username": "u", "role": role,
             "allowed_branches": ["JKT_01"]},
            settings.secret_key, algorithm=settings.algorithm)
        from fastapi.security.http import HTTPAuthorizationCredentials
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    class _FakePool:
        def __init__(self, role):
            self.role = role

        async def fetchrow(self, sql, user_id):
            return {"role": self.role, "is_active": True}

    def _patch(self, monkeypatch, role):
        pool = self._FakePool(role)

        async def _pool():
            return pool
        monkeypatch.setattr("app.core.database.get_core_pool", _pool)

    def test_admin_ditolak_403(self, monkeypatch):
        self._patch(monkeypatch, "admin")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            asyncio.run(require_user_role(self._creds("admin")))
        assert exc.value.status_code == 403
        assert "role 'user'" in exc.value.detail

    def test_user_lolos_mengembalikan_payload(self, monkeypatch):
        self._patch(monkeypatch, "user")
        payload = asyncio.run(require_user_role(self._creds("user")))
        assert payload["user_id"] == 1
        assert payload["allowed_branches"] == ["JKT_01"]

    def test_token_rusak_401(self, monkeypatch):
        from fastapi import HTTPException
        from fastapi.security.http import HTTPAuthorizationCredentials
        with pytest.raises(HTTPException) as exc:
            asyncio.run(require_user_role(HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="token-rusak")))
        assert exc.value.status_code == 401
