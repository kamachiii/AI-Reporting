import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.vanna_engine import (
    ekstrak_sql,
    susun_prompt_vanna,
    _format_ringkasan_otomatis,
    _format_rupiah_human,
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
    # Uji format Rupiah singkat (Juta, Miliar, Triliun)
    assert _format_rupiah_human(189924000000) == "Rp 189,92 Miliar"
    assert _format_rupiah_human(310578000) == "Rp 310,58 Juta"
    assert _format_rupiah_human(2500000000000) == "Rp 2,5 Triliun"
    assert _format_rupiah_human(50000) == "Rp 50.000"

    ringkasan_komparasi = _format_ringkasan_otomatis(
        [
            {"tahun": 2024, "total_transaksi": 1050, "total_pembelian": 189924000000},
            {"tahun": 2025, "total_transaksi": 419, "total_pembelian": 75578000000},
        ],
        ["tahun", "total_transaksi", "total_pembelian"]
    )
    assert "total Rp 189,92 Miliar" in ringkasan_komparasi

    ringkasan_tunggal = _format_ringkasan_otomatis(
        [{"hpunit": 310578000}],
        ["hpunit"]
    )
    assert "hpunit: Rp 310,58 Juta" in ringkasan_tunggal

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
        assert any("terpisah" in s for s in res["saran"])

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
async def test_jalankan_mode_vanna_fanout_3s():
    fake_core_pool = AsyncMock()
    fake_core_pool.fetchrow = AsyncMock(return_value=None)
    fake_core_pool.fetchval = AsyncMock(return_value=123)
    fake_core_pool.execute = AsyncMock()

    class FakeRecord(dict):
        pass

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[
        FakeRecord({"total": 100, "omzet": 50000000.0})
    ])

    fake_pool_tenant = MagicMock()
    fake_pool_tenant.acquire.return_value = _AsyncContextManager(fake_conn)
    fake_tpm = AsyncMock()
    fake_tpm.get_pool = AsyncMock(return_value=fake_pool_tenant)

    user = {"user_id": 1, "username": "testuser"}

    llm_json = json.dumps({
        "unit": "SELECT count(*) AS total_unit, sum(hjakhir) AS omzet FROM untt_penjualan WHERE batal = false;",
        "service": "SELECT count(*) AS total_pkb, sum(total_biaya) AS pendapatan FROM womt_wo WHERE batal = false;",
        "part": "SELECT count(*) AS total_item, sum(total_harga) AS total_part FROM womt_wopart;"
    })

    async def mock_llm(sys_msg, prompt, cfg):
        return f"```json\n{llm_json}\n```"

    with patch("app.services.vanna_engine.resolve_tenant", return_value={"tenant_id": 1, "branch_code": "TST_01"}), \
         patch("app.services.vanna_engine.resolve_ai_config", return_value={}), \
         patch("app.services.vanna_engine.ambil_konteks_vanna", return_value=("Context...", [])):
        res = await jalankan_mode_vanna(
            fake_core_pool, fake_tpm, user, "berapa total penjualan tahun 2025", "TST_01",
            llm_call_fn=mock_llm
        )

        assert res["is_multi_tab"] is True
        assert len(res["tabs"]) == 3
        assert res["tabs"][0]["id"] == "unit"
        assert res["tabs"][1]["id"] == "service"
        assert res["tabs"][2]["id"] == "part"
        assert "Unit Kendaraan" in res["ringkasan"]
        assert "Jasa Servis Bengkel" in res["ringkasan"]
        assert "Suku Cadang" in res["ringkasan"]


def test_annual_comparison_anti_inversion():
    from app.services.vanna_engine import _format_ringkasan_otomatis
    cols = ['tahun', 'omzet_penjualan_unit', 'volume_unit_terjual', 'omzet_servis_bengkel', 'volume_unit_entry', 'omzet_sparepart_bengkel']
    rows = [
        [2026, 944900000, 3, 0, 13, 68498000],
        [2025, 69825000000, 350, 0, 13313, 42180000000]
    ]
    summary = _format_ringkasan_otomatis(rows, cols, "bandingkan peforma tiap divisi dalam tiap tahunnya")
    assert "total Rp 3)" not in summary
    assert "total Rp 350)" not in summary
    assert "Tahun 2026: 3 unit" in summary
    assert "Tahun 2025: 350 unit" in summary


def test_is_data_cutoff_question_detection():
    from app.services.vanna_engine import _is_data_cutoff_question
    # Sesi baru tanpa konteks -> WAJIB minta klarifikasi (tidak boleh menebak 2025)
    res_no_ctx = _is_data_cutoff_question("kenapa data hanya sampai bulan 11?")
    assert res_no_ctx["needs_clarification"] is True
    assert res_no_ctx["target_year"] is None
    assert res_no_ctx["is_transaksi_terakhir"] is False

    # Multi-turn dalam sesi aktif yang memiliki konteks tahun & topik
    res_with_ctx = _is_data_cutoff_question("mengapa data cuma sampai november?", active_context={"year": 2025, "topic": "servis"})
    assert res_with_ctx["needs_clarification"] is False
    assert res_with_ctx["target_year"] == 2025
    assert res_with_ctx["topic"] == "servis"
    assert res_with_ctx["is_transaksi_terakhir"] is False

    # Pertanyaan eksplisit menyebutkan tahun
    res_explicit_year = _is_data_cutoff_question("kenapa data 2026 hanya sampai bulan 6?")
    assert res_explicit_year["needs_clarification"] is False
    assert res_explicit_year["target_year"] == 2026
    assert res_explicit_year["is_transaksi_terakhir"] is False

    # Pertanyaan transaksi terakhir eksplisit tahun
    res_last_tx = _is_data_cutoff_question("kapan transaksi terakhir tercatat tahun 2025?")
    assert res_last_tx["needs_clarification"] is False
    assert res_last_tx["target_year"] == 2025
    assert res_last_tx["is_transaksi_terakhir"] is True

    # Bukan pertanyaan cutoff
    assert _is_data_cutoff_question("tampilkan 5 mobil terlaris") is None


def test_ambil_konteks_percakapan_aktif_empty():
    import asyncio
    from app.services.vanna_engine import ambil_konteks_percakapan_aktif
    # conversation_id None -> netral tanpa bocor
    ctx = asyncio.run(ambil_konteks_percakapan_aktif(None, None))
    assert ctx == {"year": None, "topic": None, "has_prior_chat": False}


def test_rekonsiliasi_slot_percakapan():
    import asyncio
    import json
    from app.services.vanna_engine import rekonsiliasi_slot_percakapan

    class _StubPool:
        def __init__(self, assistant_content):
            self.content = assistant_content
        async def fetchrow(self, query, *args):
            return {"content": self.content}

    # Asisten sebelumnya mengirim status clarification_needed
    assistant_json = json.dumps({
        "status": "clarification_needed",
        "pending_clarification": {
            "intent": "data_cutoff",
            "original_question": "kenapa data hanya sampai bulan 11?",
            "missing_slots": ["domain", "year"],
            "captured_slots": {"month": 11}
        }
    })
    pool = _StubPool(assistant_json)

    # 1. User membalas dengan domain dan tahun: 'penjualan unit 2025'
    res_q, is_rec = asyncio.run(rekonsiliasi_slot_percakapan(pool, 10, "penjualan unit 2025"))
    assert is_rec is True
    assert res_q == "Kenapa data penjualan unit tahun 2025 hanya sampai bulan 11?"

    # 2. User membalas servis bengkel tahun 2024
    res_q2, is_rec2 = asyncio.run(rekonsiliasi_slot_percakapan(pool, 10, "servis bengkel 2024"))
    assert is_rec2 is True
    assert res_q2 == "Kenapa data servis bengkel tahun 2024 hanya sampai bulan 11?"

    # 3. User hanya menyebut tahun '2025'
    res_q3, is_rec3 = asyncio.run(rekonsiliasi_slot_percakapan(pool, 10, "tahun 2025"))
    assert is_rec3 is True
    assert res_q3 == "Kenapa data transaksi tahun 2025 hanya sampai bulan 11?"

    # 4. User berpindah topik (Topic Shift)
    res_q4, is_rec4 = asyncio.run(rekonsiliasi_slot_percakapan(pool, 10, "siapa 5 customer terbesar?"))
    assert is_rec4 is False
    assert res_q4 == "siapa 5 customer terbesar?"






