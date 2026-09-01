"""Test tenant_pool (F2.4) — LRU, reuse, close_all, tanpa DB nyata.

Connector di-inject (fake) sehingga create_pool tidak pernah menyentuh
jaringan. pytest-asyncio tidak tersedia — asyncio.run.
"""
import asyncio

import pytest

try:
    from app.core.security import encrypt_credential
    from app.services.tenant_pool import TenantPoolError, TenantPoolManager
    HAS_POOL = True
except ImportError:
    HAS_POOL = False


def _run(coro):
    return asyncio.run(coro)


class FakePoolObj:
    def __init__(self, label):
        self.label = label
        self.closed = False

    async def close(self):
        self.closed = True


class FakeConnector:
    """Mencatat kwargs pemanggilan & menghitung pool yang dibuat."""

    def __init__(self):
        self.panggilan = []
        self.pools = []

    async def __call__(self, **kwargs):
        self.panggilan.append(kwargs)
        pool = FakePoolObj(f"pool-{len(self.pools) + 1}")
        self.pools.append(pool)
        return pool


def _row(cid, password=None, **extra):
    # default: password Fernet-valid seperti hasil encrypt_credential onboarding
    if password is None:
        password = encrypt_credential("rahasia-plain")
    row = {
        "id": cid, "db_host": f"host-{cid}", "db_port": 5432,
        "db_name": f"db-{cid}", "db_username": "u_ro",
        "db_password": password, "is_active": True,
    }
    row.update(extra)
    return row


@pytest.mark.skipif(not HAS_POOL, reason="tenant_pool belum ada")
class TestTenantPoolManager:
    def test_pool_dibuat_dengan_kredensial_terdekripsi(self):
        connector = FakeConnector()
        mgr = TenantPoolManager(connector=connector)
        row = _row(1, password=encrypt_credential("password-asli"))
        pool = _run(mgr.get_pool(row))
        assert pool is connector.pools[0]
        kwargs = connector.panggilan[0]
        assert kwargs["password"] == "password-asli"  # Fernet didekripsi
        assert kwargs["database"] == "db-1"
        assert kwargs["host"] == "host-1"
        assert kwargs["max_size"] == 2  # default pool max_size

    def test_reuse_pool_per_id(self):
        connector = FakeConnector()
        mgr = TenantPoolManager(connector=connector)
        _run(mgr.get_pool(_row(1)))
        pool2 = _run(mgr.get_pool(_row(1)))
        assert len(connector.panggilan) == 1  # connector hanya sekali
        assert pool2 is connector.pools[0]
        assert mgr.jumlah_pool == 1

    def test_lru_evict_maks_pool(self):
        connector = FakeConnector()
        mgr = TenantPoolManager(connector=connector, max_pools=2)
        _run(mgr.get_pool(_row(1)))
        _run(mgr.get_pool(_row(2)))
        _run(mgr.get_pool(_row(1)))  # id 1 naik ke depan (LRU)
        _run(mgr.get_pool(_row(3)))  # evict id 2 (paling lama tak dipakai)
        assert connector.pools[1].closed is True   # id 2 tertutup
        assert connector.pools[0].closed is False  # id 1 masih hidup
        assert connector.pools[2].closed is False
        assert mgr.jumlah_pool == 2

    def test_close_all_menutup_semua(self):
        connector = FakeConnector()
        mgr = TenantPoolManager(connector=connector)
        _run(mgr.get_pool(_row(1)))
        _run(mgr.get_pool(_row(2)))
        _run(mgr.close_all())
        assert all(p.closed for p in connector.pools)
        assert mgr.jumlah_pool == 0

    def test_idle_timeout_sweep(self):
        import time
        connector = FakeConnector()
        mgr = TenantPoolManager(connector=connector, idle_timeout_seconds=10.0)
        _run(mgr.get_pool(_row(1)))
        # paksa pool id-1 "idle" lebih lama dari timeout
        mgr._pools[1]["terakhir"] = time.monotonic() - 20.0
        _run(mgr.get_pool(_row(2)))
        assert connector.pools[0].closed is True
        assert mgr.jumlah_pool == 1

    def test_is_active_false_ditolak(self):
        mgr = TenantPoolManager(connector=FakeConnector())
        with pytest.raises(TenantPoolError) as exc:
            _run(mgr.get_pool(_row(1, is_active=False)))
        assert "tidak aktif" in str(exc.value)

    def test_password_tidak_bisa_didekripsi(self):
        mgr = TenantPoolManager(connector=FakeConnector())
        with pytest.raises(TenantPoolError) as exc:
            _run(mgr.get_pool(_row(1, password="bukan-fernet")))
        assert "FERNET_KEY" in str(exc.value)

    def test_row_tanpa_id_ditolak(self):
        mgr = TenantPoolManager(connector=FakeConnector())
        with pytest.raises(TenantPoolError):
            _run(mgr.get_pool({"db_host": "x"}))

    def test_connector_gagal_propagasi_jelas(self):
        async def connector_gagal(**kwargs):
            raise RuntimeError("db down")
        mgr = TenantPoolManager(connector=connector_gagal)
        with pytest.raises(TenantPoolError) as exc:
            _run(mgr.get_pool(_row(1)))
        assert "gagal membuat pool" in str(exc.value)
