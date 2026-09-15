"""Test endpoint admin Kelola SQL Memory (QA2-01) + regresi save-pending.

Menguji:
1. GET /admin/memories (list, filter branch/status, status liar -> 400)
2. DELETE /admin/memories/{id} (sukses + audit, 404 + audit)
3. Guard require_admin_role (user -> 403)
4. Regresi QA2-01: save jawaban Vanna memakai status 'pending'
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_admin_role
from app.main import app


class FakeMemPool:
    def __init__(self):
        self.rows = [
            {"id": 1, "branch_code": "TST_01",
             "pertanyaan_ternormalisasi": "berapa omzet?",
             "sql": "SELECT 1", "status": "approved", "sumber": "vanna",
             "times_used": 5, "updated_at": None},
            {"id": 2, "branch_code": "TST_02",
             "pertanyaan_ternormalisasi": "berapa unit?",
             "sql": "SELECT 2", "status": "pending", "sumber": "vanna",
             "times_used": 1, "updated_at": None},
        ]
        self.audits = []

    async def fetchval(self, query, *args):
        if "COUNT(*)" in query:
            return len(self.rows)
        return 0

    async def fetch(self, query, *args):
        if "FROM sql_memory" in query and "JOIN tenants" in query:
            if "WHERE m.id = " in query:
                for r in self.rows:
                    if r["id"] == args[0]:
                        return r
                return None
            return list(self.rows)
        return []

    async def fetchrow(self, query, *args):
        rows = await self.fetch(query, *args)
        if isinstance(rows, dict):
            return rows
        return rows[0] if rows else None

    async def execute(self, query, *args):
        if query.strip().startswith("DELETE FROM sql_memory"):
            before = len(self.rows)
            self.rows = [r for r in self.rows if r["id"] != args[0]]
            return "DELETE 1" if len(self.rows) < before else "DELETE 0"
        if "UPDATE sql_memory SET status" in query:
            for r in self.rows:
                if r["id"] == args[0]:
                    return "UPDATE 1"
            return "UPDATE 0"
        if query.strip().startswith("INSERT INTO audit_logs"):
            # Tiru constraint NOT NULL audit_logs.branch_code ($2):
            # audit tanpa cabang HARUS gagal seperti di Postgres asli.
            assert args[1] is not None, \
                "audit branch_code null melanggar NOT NULL"
            self.audits.append(args)
            return "INSERT 1"
        return "OK"


@pytest.fixture
def client_admin(monkeypatch):
    pool = FakeMemPool()
    from app.routers.admin import memories as mem_router

    async def _pool():
        return pool

    monkeypatch.setattr(mem_router, "get_core_pool", _pool)

    app.dependency_overrides[require_admin_role] = lambda: {
        "user_id": 1, "username": "admin", "role": "admin"
    }
    client = TestClient(app)
    yield client, pool
    app.dependency_overrides.clear()


def test_list_memories(client_admin):
    client, _ = client_admin
    resp = client.get("/admin/memories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["items"][0]["branch_code"] in ("TST_01", "TST_02")


def test_list_memories_status_liar_ditolak(client_admin):
    client, _ = client_admin
    assert client.get("/admin/memories?status=rusak").status_code == 400


def test_delete_memory_sukses_dan_audit(client_admin):
    client, pool = client_admin
    resp = client.delete("/admin/memories/1")
    assert resp.status_code == 200
    assert "berhasil dihapus" in resp.json()["message"]
    assert all(r["id"] != 1 for r in pool.rows)
    assert len(pool.audits) == 1  # penghapusan tercatat di audit


def test_delete_memory_tidak_ada_404_dan_audit(client_admin):
    client, pool = client_admin
    assert client.delete("/admin/memories/999").status_code == 404
    assert len(pool.audits) == 1  # kegagalan pun tercatat


def test_pulihkan_stale_jadi_pending(client_admin):
    """Anti false-stale K1: stale -> pending (wajib konfirmasi ulang)."""
    client, pool = client_admin
    pool.rows.append({"id": 3, "branch_code": "TST_01",
                      "pertanyaan_ternormalisasi": "q?",
                      "sql": "SELECT 3", "status": "stale", "sumber": "vanna",
                      "times_used": 0, "updated_at": None})
    resp = client.post("/admin/memories/3/pulihkan")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_pulihkan_bukan_stale_409(client_admin):
    client, _ = client_admin
    assert client.post("/admin/memories/1/pulihkan").status_code == 409


def test_pulihkan_tidak_ada_404(client_admin):
    client, _ = client_admin
    assert client.post("/admin/memories/999/pulihkan").status_code == 404


def test_memories_berada_di_belakang_guard_admin():
    """Endpoint wajib memakai require_admin_role (RBAC live dibuktikan 51/51
    + 2 endpoint baru di sweep QA Tahap 1)."""
    paths = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in ("/admin/memories", "/admin/memories/{memory_id}"):
            paths.add(path)
            dependant = getattr(route, "dependant", None)
            sub = getattr(dependant, "dependencies", []) if dependant else []
            calls = [getattr(d, "call", None) for d in sub]
            assert require_admin_role in calls, \
                f"{path} tidak memakai require_admin_role"
    assert paths == {"/admin/memories", "/admin/memories/{memory_id}"}


def test_save_vanna_memakai_status_pending():
    """Regresi QA2-01: jawaban Vanna baru WAJIB 'pending', bukan 'approved'."""
    src = (Path(__file__).parent.parent / "app" / "services"
           / "vanna_engine.py").read_text(encoding="utf-8")
    idx = src.find("INSERT INTO sql_memory")
    assert idx != -1, "query simpan memori hilang dari vanna_engine"
    blok = src[idx:idx + 600]
    assert "'pending'" in blok, "save Vanna harus status pending (QA2-01)"
    assert "'approved'" not in blok, "save Vanna dilarang auto-approved"
