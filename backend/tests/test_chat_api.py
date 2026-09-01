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
        normalisasi_pertanyaan, proses_pertanyaan)
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
                    times_used=0):
        self.next_id += 1
        self.sql_memory.append({
            "id": self.next_id, "tenant_id": 3,
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
