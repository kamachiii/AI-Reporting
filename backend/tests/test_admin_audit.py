"""Test decorator audit_admin (QA1-01).

Kontrak:
1. Sukses -> audit success + hasil asli kembali apa adanya.
2. HTTPException -> audit error berisi detail + exception dilempar ulang.
3. Exception umum -> audit error + dilempar ulang (handler bawaan jadi 500).
4. Audit gagal (DB audit error) -> operasi TETAP sukses (audit tak memblokir).
5. target="result.x.y" di-resolve dari hasil sukses.
"""
import pytest
from fastapi import HTTPException

from app.services import admin_audit as aa


class FakePool:
    def __init__(self, gagal_audit=False):
        self.audits = []
        self.gagal_audit = gagal_audit

    async def execute(self, query, *args):
        if "INSERT INTO audit_logs" in query:
            if self.gagal_audit:
                raise RuntimeError("DB audit mati")
            self.audits.append(args)
            return "INSERT 1"
        return "OK"


@pytest.fixture
def pool():
    return FakePool()


def _jalan(pool):
    async def _get():
        return pool
    return _get


def test_sukses_audit_dan_hasil_utuh(pool, monkeypatch):
    monkeypatch.setattr(aa, "get_core_pool", _jalan(pool))

    @aa.audit_admin("uji-buat", target="payload.code")
    async def buat(payload, user=None):
        return {"code": payload["code"]}

    import asyncio
    hasil = asyncio.run(
        buat({"code": "X1"}, user={"user_id": 1}))
    assert hasil == {"code": "X1"}
    assert len(pool.audits) == 1
    user_id, branch, prompt, _f, _sql, _ms, status, _err = pool.audits[0]
    assert (user_id, branch, status) == (1, "", "success")
    assert prompt == "[uji-buat] X1"


def test_http_exception_audit_error_dan_raise(pool, monkeypatch):
    monkeypatch.setattr(aa, "get_core_pool", _jalan(pool))

    @aa.audit_admin("uji-hapus", target="code")
    async def hapus(code, user=None):
        raise HTTPException(status_code=404, detail="Tidak ada")

    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hapus("X9", user={"user_id": 2}))
    assert exc.value.status_code == 404
    assert len(pool.audits) == 1
    assert pool.audits[0][6] == "error"
    assert pool.audits[0][7] == "Tidak ada"


def test_exception_umum_audit_lalu_raise(pool, monkeypatch):
    monkeypatch.setattr(aa, "get_core_pool", _jalan(pool))

    @aa.audit_admin("uji-rusak", target="code")
    async def rusak(code, user=None):
        raise ValueError("meledak")

    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(rusak("X9"))
    assert len(pool.audits) == 1
    assert pool.audits[0][6] == "error"


def test_audit_gagal_operasi_tetap_sukses(monkeypatch):
    pool = FakePool(gagal_audit=True)
    monkeypatch.setattr(aa, "get_core_pool", _jalan(pool))

    @aa.audit_admin("uji-tahan", target="code")
    async def tahan(code, user=None):
        return "ok"

    import asyncio
    assert asyncio.run(tahan("X1")) == "ok"
    assert pool.audits == []


def test_target_dari_hasil(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(aa, "get_core_pool", _jalan(pool))

    @aa.audit_admin("uji-buat", target="result.item.id")
    async def buat(payload, user=None):
        return {"item": {"id": 77}}

    import asyncio
    asyncio.run(buat({"x": 1}))
    assert pool.audits[0][2] == "[uji-buat] 77"
