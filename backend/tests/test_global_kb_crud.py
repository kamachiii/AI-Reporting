"""Test CRUD API untuk Global Knowledge Base (F3.1).

Menguji:
1. POST /admin/global-kb/items (validasi sukses & validasi strict extra='forbid')
2. GET /admin/global-kb/items/{id} (sukses & 404)
3. PUT /admin/global-kb/items/{id} (update sukses & 404)
4. DELETE /admin/global-kb/items/{id} (hapus sukses & 404)
5. Guard require_admin_role
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import require_admin_role
from app.main import app


class FakeGlobalKBPool:
    def __init__(self):
        self.items = []
        self._next_id = 1

    async def fetchval(self, query, *args):
        if "COUNT(*)" in query:
            if "kind = 'text'" in query:
                return len([i for i in self.items if i["kind"] == "text"])
            if "kind = 'example'" in query:
                return len([i for i in self.items if i["kind"] == "example"])
            return len(self.items)
        return 0

    async def fetch(self, query, *args):
        return self.items

    async def fetchrow(self, query, *args):
        if "INSERT INTO global_knowledge_base" in query:
            ext_id, kind, content, question, sql_example, meta = args
            item = {
                "id": self._next_id,
                "external_id": ext_id,
                "kind": kind,
                "content": content,
                "question": question,
                "sql_example": sql_example,
                "metadata": meta,
                "created_at": None,
                "updated_at": None,
            }
            self._next_id += 1
            self.items.append(item)
            return item
        elif "UPDATE global_knowledge_base" in query:
            kind, content, question, sql_example, meta, item_id = args
            for item in self.items:
                if item["id"] == item_id:
                    item["kind"] = kind
                    item["content"] = content
                    item["question"] = question
                    item["sql_example"] = sql_example
                    item["metadata"] = meta
                    return item
            return None
        elif "SELECT" in query and "WHERE id =" in query:
            item_id = args[0]
            for item in self.items:
                if item["id"] == item_id:
                    return item
            return None
        return None

    async def execute(self, query, *args):
        if "DELETE FROM global_knowledge_base" in query:
            item_id = args[0]
            before = len(self.items)
            self.items = [i for i in self.items if i["id"] != item_id]
            if len(self.items) < before:
                return "DELETE 1"
            return "DELETE 0"
        return "OK"


@pytest.fixture
def client_admin(monkeypatch):
    pool = FakeGlobalKBPool()
    from app.routers.admin import global_kb as gkb_router

    async def _pool():
        return pool

    monkeypatch.setattr(gkb_router, "get_core_pool", _pool)

    app.dependency_overrides[require_admin_role] = lambda: {
        "user_id": 1, "username": "admin", "role": "admin"
    }
    client = TestClient(app)
    yield client, pool
    app.dependency_overrides.clear()


def test_create_global_kb_item_sukses(client_admin):
    client, pool = client_admin
    payload = {
        "kind": "text",
        "content": "Definisi omzet adalah total penjualan kotor.",
        "metadata": {"sumber": "manual"}
    }
    resp = client.post("/admin/global-kb/items", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["message"] == "Item KB global berhasil dibuat"
    assert data["item"]["kind"] == "text"
    assert data["item"]["content"] == payload["content"]
    assert data["item"]["external_id"].startswith("manual_")


def test_create_global_kb_item_field_asing_ditolak_422(client_admin):
    client, pool = client_admin
    payload = {
        "kind": "text",
        "content": "Definisi test",
        "field_ilegal": "hacker"  # Dilarang oleh extra='forbid'
    }
    resp = client.post("/admin/global-kb/items", json=payload)
    assert resp.status_code == 422


def test_get_global_kb_item_detail(client_admin):
    client, pool = client_admin
    # Buat item dulu
    post_resp = client.post("/admin/global-kb/items", json={
        "kind": "example",
        "content": "Contoh omzet",
        "question": "Berapa omzet?",
        "sql_example": "SELECT SUM(total) FROM penjualan"
    })
    item_id = post_resp.json()["item"]["id"]

    resp = client.get(f"/admin/global-kb/items/{item_id}")
    assert resp.status_code == 200
    assert resp.json()["question"] == "Berapa omzet?"

    # 404 untuk ID tidak ada
    assert client.get("/admin/global-kb/items/9999").status_code == 404


def test_update_global_kb_item(client_admin):
    client, pool = client_admin
    post_resp = client.post("/admin/global-kb/items", json={
        "kind": "text",
        "content": "Versi 1"
    })
    item_id = post_resp.json()["item"]["id"]

    put_resp = client.put(f"/admin/global-kb/items/{item_id}", json={
        "content": "Versi 2 Terupdate"
    })
    assert put_resp.status_code == 200
    assert put_resp.json()["item"]["content"] == "Versi 2 Terupdate"


def test_delete_global_kb_item(client_admin):
    client, pool = client_admin
    post_resp = client.post("/admin/global-kb/items", json={
        "kind": "text",
        "content": "Mau dihapus"
    })
    item_id = post_resp.json()["item"]["id"]

    del_resp = client.delete(f"/admin/global-kb/items/{item_id}")
    assert del_resp.status_code == 200
    assert "berhasil dihapus" in del_resp.json()["message"]

    # Delete ulang -> 404
    assert client.delete(f"/admin/global-kb/items/{item_id}").status_code == 404
