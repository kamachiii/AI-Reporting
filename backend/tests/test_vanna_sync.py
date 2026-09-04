"""Test vanna_sync (F3) — sinkronisasi KB global dari Vanna API.

Memastikan:
- _login_vanna login dengan benar
- _fetch_semua_items pagination
- sync_dari_vanna upsert data & handling orphan
- VannaSyncError saat HTTP gagal
"""
import asyncio
import httpx
import pytest

from app.services.vanna_sync import (
    VannaSyncError,
    _login_vanna,
    _fetch_semua_items,
    sync_dari_vanna,
)


def _run(coro):
    return asyncio.run(coro)


class _StubConn:
    def __init__(self):
        self.inserted_count = 0
        self.deleted_count = 0
        self.executed_queries = []

    async def fetchrow(self, query, *args):
        self.executed_queries.append((query, args))
        return {"is_inserted": True}

    async def fetch(self, query, *args):
        self.executed_queries.append((query, args))
        return [{"id": 1}]

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        return _Tx()


class _StubPool:
    def __init__(self, conn=None):
        self.conn = conn or _StubConn()

    def acquire(self):
        conn = self.conn
        class _Acq:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *args):
                pass
        return _Acq()


class TestVannaSync:
    def test_login_sukses(self):
        def handler(request: httpx.Request):
            if request.url.path == "/login":
                return httpx.Response(200, text="OK")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async def _test():
            async with httpx.AsyncClient(transport=transport) as client:
                await _login_vanna(client, "http://vanna-test", "user", "pass")

        _run(_test())

    def test_login_gagal_raise_error(self):
        def handler(request: httpx.Request):
            return httpx.Response(401, text="Unauthorized")

        transport = httpx.MockTransport(handler)
        async def _test():
            async with httpx.AsyncClient(transport=transport) as client:
                with pytest.raises(VannaSyncError) as exc:
                    await _login_vanna(client, "http://vanna-test", "user", "pass")
                assert "Login failed" in str(exc.value)

        _run(_test())

    def test_fetch_semua_items_pagination(self):
        def handler(request: httpx.Request):
            if request.url.path == "/api/kb/items":
                offset = int(request.url.params.get("offset", 0))
                if offset == 0:
                    return httpx.Response(200, json={
                        "total": 150, "limit": 100, "offset": 0,
                        "items": [{"id": f"item-{i}", "kind": "text", "content": f"Content {i}"} for i in range(100)]
                    })
                elif offset == 100:
                    return httpx.Response(200, json={
                        "total": 150, "limit": 100, "offset": 100,
                        "items": [{"id": f"item-{i}", "kind": "text", "content": f"Content {i}"} for i in range(100, 150)]
                    })
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async def _test():
            async with httpx.AsyncClient(transport=transport) as client:
                items = await _fetch_semua_items(client, "http://vanna-test")
                assert len(items) == 150

        _run(_test())

    def test_sync_dari_vanna_end_to_end(self, monkeypatch):
        # Mock httpx.AsyncClient to use MockTransport
        def handler(request: httpx.Request):
            if request.url.path == "/login":
                return httpx.Response(200, text="OK")
            if request.url.path == "/api/kb/items":
                return httpx.Response(200, json={
                    "total": 2, "limit": 100, "offset": 0,
                    "items": [
                        {"id": "t1", "kind": "text", "content": "Table buyer columns: id"},
                        {"id": "e1", "kind": "example", "question": "how many?", "sql": "SELECT COUNT(*)", "content": "how many?"}
                    ]
                })
            return httpx.Response(404)

        orig_client_init = httpx.AsyncClient.__init__
        def patched_client_init(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            orig_client_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_client_init)

        stub_pool = _StubPool()
        stats = _run(sync_dari_vanna(stub_pool, "http://vanna-test", "user", "pass"))

        assert stats["total_fetched"] == 2
        assert stats["inserted"] == 2
        assert stats["deleted"] == 1
        assert stats["errors"] == 0
