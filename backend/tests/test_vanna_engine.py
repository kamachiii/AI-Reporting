import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.vanna_engine import (
    ekstrak_sql,
    susun_prompt_vanna,
    _format_ringkasan_otomatis,
    jalankan_mode_vanna,
)

def test_ekstrak_sql():
    raw_markdown = "```sql\nSELECT * FROM untt_pembelian;\n```"
    assert ekstrak_sql(raw_markdown) == "SELECT * FROM untt_pembelian"

    raw_no_fence = "SELECT count(*) FROM untt_spk;"
    assert ekstrak_sql(raw_no_fence) == "SELECT count(*) FROM untt_spk"

    raw_json = '{"sql": "SELECT sum(hjakhir) FROM untt_penjualan;"}'
    assert ekstrak_sql(raw_json) == "SELECT sum(hjakhir) FROM untt_penjualan"

def test_susun_prompt_vanna():
    p = susun_prompt_vanna("berapa pembelian?", "Table untt_pembelian columns: nomor")
    assert "You are a Postgres expert" in p
    assert "Table untt_pembelian" in p
    assert "berapa pembelian?" in p

def test_format_ringkasan_otomatis():
    assert _format_ringkasan_otomatis([], []) == "Tidak ada data yang ditemukan untuk kueri ini."
    assert "Perbandingan per tahun" in _format_ringkasan_otomatis(
        [{"tahun": 2025, "total": 100}, {"tahun": 2026, "total": 50}],
        ["tahun", "total"]
    )
    assert "Berhasil menampilkan 3 baris" in _format_ringkasan_otomatis(
        [{"a": 1}, {"a": 2}, {"a": 3}],
        ["a"]
    )

class _AsyncContextManager:
    def __init__(self, val):
        self.val = val
    async def __aenter__(self):
        return self.val
    async def __aexit__(self, *args):
        pass

@pytest.mark.anyio
async def test_jalankan_mode_vanna_mock():
    fake_core_pool = AsyncMock()
    fake_core_pool.fetchrow = AsyncMock(return_value=None)
    fake_core_pool.fetch = AsyncMock(return_value=[{"content": "Table untt_pembelian columns: nomor"}])
    fake_core_pool.fetchval = AsyncMock(return_value=1)
    fake_core_pool.execute = AsyncMock()
    
    fake_tpm = AsyncMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[{"tahun": 2025, "total": 1000}])
    
    fake_pool_tenant = MagicMock()
    fake_pool_tenant.acquire.return_value = _AsyncContextManager(fake_conn)
    fake_tpm.get_pool = AsyncMock(return_value=fake_pool_tenant)

    user = {"user_id": 1, "username": "testuser"}
    
    with patch("app.services.vanna_engine.resolve_tenant", return_value={"tenant_id": 1, "branch_code": "TST_01"}), \
         patch("app.services.vanna_engine.resolve_ai_config", return_value={"model": "test-model"}), \
         patch("app.services.vanna_engine.ambil_konteks_vanna", return_value=("ctx", [])):
        
        async def fake_llm(sys, usr, cfg):
            return "```sql\nSELECT tahun, total FROM vw_pembelian;\n```"

        res = await jalankan_mode_vanna(
            fake_core_pool, fake_tpm, user, "bandingkan pembelian unit mobil 2025 dan 2026", "TST_01",
            llm_call_fn=fake_llm
        )

        assert res["source"] == "vanna"
        assert res["confidence"] == "A"
        assert "SELECT tahun, total" in res["sql"]
        assert res["row_count"] == 1
        assert res["saran"] == []

@pytest.mark.anyio
async def test_jalankan_mode_vanna_memory_replay():
    fake_core_pool = AsyncMock()
    # SQL Memory hit -> replay dengan 0 panggilan LLM!
    fake_core_pool.fetchrow = AsyncMock(return_value={
        "id": 99,
        "sql": "SELECT tahun, total FROM untt_penjualan WHERE tahun IN (2025, 2026);",
        "ringkasan": "Perbandingan per tahun: 2025 vs 2026.",
        "status": "approved"
    })
    fake_core_pool.execute = AsyncMock()
    
    fake_tpm = AsyncMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[{"tahun": 2025, "total": 2000}])
    fake_pool_tenant = MagicMock()
    fake_pool_tenant.acquire.return_value = _AsyncContextManager(fake_conn)
    fake_tpm.get_pool = AsyncMock(return_value=fake_pool_tenant)

    user = {"user_id": 1, "username": "testuser"}
    
    with patch("app.services.vanna_engine.resolve_tenant", return_value={"tenant_id": 1, "branch_code": "TST_01"}):
        res = await jalankan_mode_vanna(
            fake_core_pool, fake_tpm, user, "berikan data penjualan 2025 vs 2026", "TST_01"
        )

        assert res["source"] == "memory"
        assert res["confidence"] == "A"
        assert res["memory_id"] == 99
        assert "untt_penjualan" in res["sql"]


@pytest.mark.anyio
async def test_jalankan_mode_vanna_clarification():
    fake_core_pool = AsyncMock()
    # SQL Memory miss
    fake_core_pool.fetchrow = AsyncMock(return_value=None)
    fake_core_pool.fetchval = AsyncMock(return_value=123)
    fake_core_pool.execute = AsyncMock()

    fake_tpm = AsyncMock()
    user = {"user_id": 1, "username": "testuser"}

    with patch("app.services.vanna_engine.resolve_tenant", return_value={"tenant_id": 1, "branch_code": "TST_01"}):
        res = await jalankan_mode_vanna(
            fake_core_pool, fake_tpm, user, "berapa total penjualan tahun 2025", "TST_01"
        )

        assert res["source"] == "clarification"
        assert res["status"] == "clarification_needed"
        assert "divisi bisnis dealer" in res["clarification_message"]
        assert len(res["options"]) == 3
        assert res["options"][0]["label"] == "Penjualan Unit Mobil"
        assert res["options"][1]["label"] == "Penjualan Sparepart / Suku Cadang"
        assert res["options"][2]["label"] == "Total Gabungan (Unit & Sparepart)"

