"""Test antrean promosi KB (penyatuan governance).

1. Confirm pending->approved pertama -> nominasi dibuat.
2. Confirm kedua pola sama -> TIDAK duplikat.
3. Endpoint setuju/tolak + guard + audit (TestClient, fake pool).
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import require_admin_role
from app.main import app


class FakeCore:
    def __init__(self):
        self.memori = {"id": 50, "status": "pending",
                       "pertanyaan_ternormalisasi": "berapa omzet 2025?",
                       "sql": "SELECT 1"}
        self.promosi = []
        self.kb = {"glossary": [], "catatan_kolom": {}, "nilai_map": {},
                   "contoh_tanya": [], "tabel_dilarang": [],
                   "tabel_diizinkan": [], "kolom_dikecualikan": [],
                   "relasi_tabel": []}
        self.audits = []
        self._pid = 1

    async def fetchval(self, query, *args):
        if "FROM tenants WHERE branch_code" in query:
            return 9
        if "FROM promosi_kb WHERE tenant_id" in query:
            return 1 if any(
                p["tenant_id"] == args[0] and p["pertanyaan"] == args[1]
                and p["status"] in ("diusulkan", "disetujui")
                for p in self.promosi) else None
        return None

    async def fetchrow(self, query, *args):
        if "FROM sql_memory WHERE id" in query:
            if args[0] == 50:
                return dict(self.memori)
            return None
        if "SELECT t.branch_code FROM promosi_kb" in query:
            for p in self.promosi:
                if p["id"] == args[0]:
                    return {"branch_code": "TST_02"}
            return None
        if "FROM promosi_kb" in query and "JOIN tenants" in query:
            for p in self.promosi:
                if p["id"] == args[0]:
                    r = dict(p)
                    r["branch_code"] = "TST_02"
                    r["schema_config_json"] = {"tables": {}}
                    r["knowledge_base"] = dict(self.kb)
                    return r
            return None
        if "FROM promosi_kb WHERE id" in query:
            for p in self.promosi:
                if p["id"] == args[0]:
                    return dict(p)
            return None
        return None

    async def fetch(self, query, *args):
        if "COUNT(*) FROM promosi_kb" in query:
            return 0
        if "FROM promosi_kb p" in query:
            return []
        return []

    async def execute(self, query, *args):
        if query.strip().startswith("UPDATE sql_memory"):
            self.memori["status"] = args[0]
            return "UPDATE 1"
        if "INSERT INTO promosi_kb" in query:
            self.promosi.append({
                "id": self._pid, "tenant_id": args[0],
                "memory_id": args[1], "pertanyaan": args[2], "sql": args[3],
                "status": "diusulkan", "dibuat_oleh": args[4],
                "diputus_oleh": None, "alasan": None,
                "created_at": None, "updated_at": None})
            self._pid += 1
            return "INSERT 1"
        if query.strip().startswith("INSERT INTO audit_logs"):
            self.audits.append(args)
            return "INSERT 1"
        if "UPDATE promosi_kb SET status" in query:
            return "UPDATE 1"
        if "UPDATE tenants SET knowledge_base" in query:
            import json as _j
            self.kb = _j.loads(args[1])
            return "UPDATE 1"
        return "OK"


@pytest.fixture
def pool():
    return FakeCore()


def test_confirm_pertama_menominasikan(pool):
    import asyncio
    from app.services import chat_pipeline as cp

    user = {"user_id": 6, "username": "tester03"}
    out = asyncio.run(cp.ubah_status_memory(
        pool, user, "TST_02", 50, "confirm"))
    assert out == {"ok": True, "status": "approved"}
    assert len(pool.promosi) == 1
    assert pool.promosi[0]["pertanyaan"] == "berapa omzet 2025?"
    assert pool.promosi[0]["status"] == "diusulkan"


def test_confirm_kedua_tidak_duplikat(pool):
    import asyncio
    from app.services import chat_pipeline as cp

    user = {"user_id": 6, "username": "tester03"}
    asyncio.run(cp.ubah_status_memory(pool, user, "TST_02", 50, "confirm"))
    pool.memori["status"] = "pending"
    asyncio.run(cp.ubah_status_memory(pool, user, "TST_02", 50, "confirm"))
    assert len(pool.promosi) == 1


@pytest.fixture
def client_admin(monkeypatch):
    pool = FakeCore()
    from app.routers.admin import promosi as prom_router

    async def _pool():
        return pool

    monkeypatch.setattr(prom_router, "get_core_pool", _pool)
    app.dependency_overrides[require_admin_role] = lambda: {
        "user_id": 1, "username": "admin", "role": "admin"}
    client = TestClient(app)
    yield client, pool
    app.dependency_overrides.clear()


def _isi_satu(pool):
    pool.promosi.append({
        "id": 7, "tenant_id": 9, "memory_id": 50,
        "pertanyaan": "berapa omzet 2025?", "sql": "SELECT 1",
        "status": "diusulkan", "dibuat_oleh": 6, "diputus_oleh": None,
        "alasan": None, "created_at": None, "updated_at": None})


def test_list_dan_tolak(client_admin):
    client, pool = client_admin
    _isi_satu(pool)
    r = client.get("/admin/promosi")
    assert r.status_code == 200
    assert r.json()["total"] == 0  # fake fetch mengembalikan list kosong
    r = client.post("/admin/promosi/7/tolak", json={"alasan": "salah"})
    assert r.status_code == 200
    assert any("promosi-tolak" in str(a) for a in pool.audits)
    # tolak kedua kali pada status non-diusulkan tetap konsisten
    pool.promosi[0]["status"] = "ditolak"
    r = client.post("/admin/promosi/7/tolak", json={})
    assert r.status_code == 409


def test_setuju_verifikasi_gagal_terkendali(client_admin):
    client, pool = client_admin
    _isi_satu(pool)
    # Skema fake kosong -> verifikasi menolak -> 422 terkendali (bukan 500)
    r = client.post("/admin/promosi/7/setuju")
    assert r.status_code in (200, 422)
    assert r.status_code == 422
