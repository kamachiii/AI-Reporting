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
            fake_core_pool, fake_tpm, user, "tampilkan 5 model mobil terlaris tahun 2025", "TST_01",
            llm_call_fn=fake_llm
        )

        assert res["source"] == "vanna"
        assert res["confidence"] == "A"
        assert "SELECT tahun, total" in res["sql"]
        assert res["row_count"] == 1


@pytest.mark.anyio
async def test_jalankan_mode_vanna_komparasi_deterministik():
    fake_core_pool = AsyncMock()
    fake_core_pool.fetchrow = AsyncMock(return_value=None)
    fake_core_pool.fetch = AsyncMock(return_value=[])
    fake_core_pool.fetchval = AsyncMock(return_value=1)
    fake_core_pool.execute = AsyncMock()

    fake_tpm = AsyncMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[
        {"tahun": 2020, "unit_terjual": 870, "total_omzet": 173565000000},
        {"tahun": 2021, "unit_terjual": 777, "total_omzet": 155011500000},
        {"tahun": 2022, "unit_terjual": 888, "total_omzet": 177156000000},
    ])

    fake_pool_tenant = MagicMock()
    fake_pool_tenant.acquire.return_value = _AsyncContextManager(fake_conn)
    fake_tpm.get_pool = AsyncMock(return_value=fake_pool_tenant)

    user = {"user_id": 1, "username": "testuser"}

    with patch("app.services.vanna_engine.resolve_tenant", return_value={"tenant_id": 1, "branch_code": "TST_01"}), \
         patch("app.services.vanna_engine.resolve_ai_config", return_value={"model": "test-model"}):

        # Kueri komparasi 3 tahun eliptikal: 0 panggilan LLM, deterministik ke untt_penjualan
        llm_called = False
        async def fake_llm(sys, usr, cfg):
            nonlocal llm_called
            llm_called = True
            return "SELECT 1;"

        res = await jalankan_mode_vanna(
            fake_core_pool, fake_tpm, user, "sekarang coba bandingkan 2020 vs 2021 vs 2022", "TST_01",
            inherited_topic="penjualan",
            llm_call_fn=fake_llm
        )

        assert res["source"] == "vanna"
        assert res["confidence"] == "A"
        assert llm_called is False  # Membuktikan 0 LLM token
        assert "untt_penjualan" in res["sql"]
        assert "IN (2020, 2021, 2022)" in res["sql"]
        assert res["is_comparison"] is True
        assert len(res["comparison_meta"]["periods"]) == 3
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
        "sub_mobil": "SELECT count(*) AS total_unit, sum(hjakhir) AS omzet FROM untt_penjualan WHERE batal = false;",
        "sub_servis": "SELECT count(*) AS total_pkb, sum(total_biaya) AS pendapatan FROM womt_wo WHERE batal = false;",
    })

    async def mock_llm(sys_msg, prompt, cfg):
        return f"```json\n{llm_json}\n```"

    with patch("app.services.vanna_engine.resolve_tenant", return_value={"tenant_id": 1, "branch_code": "TST_01"}), \
         patch("app.services.vanna_engine.resolve_ai_config", return_value={}), \
         patch("app.services.vanna_engine.ambil_konteks_vanna", return_value=("Context...", [])):
        res = await jalankan_mode_vanna(
            fake_core_pool, fake_tpm, user, "tampilkan penjualan mobil dan servis bengkel", "TST_01",
            llm_call_fn=mock_llm
        )

        assert res["is_multi_tab"] is True
        assert len(res["tabs"]) == 2
        assert res["tabs"][0]["id"] == "sub_mobil"
        assert res["tabs"][1]["id"] == "sub_servis"
        assert "Unit Kendaraan" in res["ringkasan"] or "Penjualan" in res["ringkasan"]
        assert "Jasa Servis Bengkel" in res["ringkasan"] or "Servis" in res["ringkasan"]


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


def test_is_general_guide_question():
    from app.services.vanna_engine import _is_general_guide_question

    # Sapaan & kueri panduan umum (termasuk variasi alohaa & informal)
    assert _is_general_guide_question("alohaa") is True
    assert _is_general_guide_question("aloha") is True
    assert _is_general_guide_question("halooo") is True
    assert _is_general_guide_question("kasih aku dong data data") is True
    assert _is_general_guide_question("minta data dong") is True
    assert _is_general_guide_question("tampilkan data") is True
    assert _is_general_guide_question("ada data apa aja di sini?") is True
    assert _is_general_guide_question("kamu bisa apa saja?") is True
    assert _is_general_guide_question("halo") is True
    assert _is_general_guide_question("hai min") is True
    assert _is_general_guide_question("selamat pagi") is True
    assert _is_general_guide_question("oi") is True
    assert _is_general_guide_question("apa kabar") is True

    # Kueri data spesifik tidak boleh tertangkap
    assert _is_general_guide_question("tampilkan 5 mobil terlaris") is False
    assert _is_general_guide_question("tampilkan data penjualan 2025") is False
    assert _is_general_guide_question("berapa total pendapatan servis bengkel?") is False
    assert _is_general_guide_question("siapa customer terbesar") is False


def test_is_explanatory_question():
    from app.services.vanna_engine import _is_explanatory_question

    # Pertanyaan eksplanatori tabel / data sebelumnya
    assert _is_explanatory_question("loh data apa ini?") is True
    assert _is_explanatory_question("ini data apa?") is True
    assert _is_explanatory_question("data apa ini?") is True
    assert _is_explanatory_question("maksud tabel ini apa?") is True
    assert _is_explanatory_question("jelaskan data di atas") is True
    assert _is_explanatory_question("jelaskan tabel ini") is True
    assert _is_explanatory_question("apa maksud kolom hjakhir?") is True
    assert _is_explanatory_question("kenapa datanya seperti ini?") is True

    # Kueri data baru tidak boleh tertangkap
    assert _is_explanatory_question("tampilkan 5 mobil terlaris") is False
    assert _is_explanatory_question("berapa omzet penjualan tahun 2025?") is False
    assert _is_explanatory_question("daftar suku cadang fast moving") is False


class _StubCorePool:
    def __init__(self, assistant_content=None):
        self.content = assistant_content
    async def fetchrow(self, query, *args):
        if "FROM messages" in query:
            if self.content is not None:
                return {"content": self.content}
            return None
        if "FROM conversations" in query:
            return {"id": 99}
        return None
    async def fetchval(self, query, *args):
        return 99
    async def execute(self, query, *args):
        return "INSERT 0 1"


def test_tangani_kueri_panduan_umum_dan_eksplanatori():
    import asyncio
    import json
    from app.services.vanna_engine import tangani_kueri_panduan_umum, tangani_kueri_eksplanatori

    pool = _StubCorePool()

    # 1. Test Mode Panduan Umum
    res_guide = asyncio.run(
        tangani_kueri_panduan_umum(pool, 99, "kasih aku dong data data", 1, "TST_01", 0.0)
    )
    assert res_guide["is_conversational_text"] is True
    assert res_guide["metode"] == "conversational_guide"
    assert res_guide["sql"] == ""
    assert res_guide["rows"] == []
    assert "Penjualan Unit" in res_guide["ringkasan"]
    assert "Jasa Servis Bengkel" in res_guide["ringkasan"]
    assert "untt_penjualan" not in res_guide["ringkasan"]
    assert "srvt_wo" not in res_guide["ringkasan"]
    assert "glbm_customer" not in res_guide["ringkasan"]
    assert len(res_guide["saran"]) >= 3

    # 2. Test Mode Eksplanatori ketika ada tabel untt_penjualan sebelumnya
    prev_asst_content = json.dumps({
        "question": "5 mobil terlaris",
        "sql": "SELECT nama_model, total_unit, hjakhir FROM untt_penjualan LIMIT 5",
        "columns": ["nama_model", "total_unit", "hjakhir"],
        "rows": [["Avanza", 10, 250000000]],
        "row_count": 1,
        "ringkasan": "Menampilkan 5 mobil terlaris"
    })
    pool_with_prev = _StubCorePool(prev_asst_content)

    res_explan = asyncio.run(
        tangani_kueri_eksplanatori(pool_with_prev, 99, "loh data apa ini?", 1, "TST_01", 0.0)
    )
    assert res_explan["is_conversational_text"] is True
    assert res_explan["metode"] == "conversational_explanation"
    assert res_explan["sql"] == ""
    assert res_explan["rows"] == []
    assert "Penjualan Unit Kendaraan" in res_explan["ringkasan"]
    assert "nama_model" in res_explan["ringkasan"]
    assert "untt_penjualan" not in res_explan["ringkasan"]
    assert "tabel `" not in res_explan["ringkasan"]
    assert len(res_explan["saran"]) >= 3

    # 3. Test Mode Eksplanatori ketika tidak ada pesan sebelumnya (sesi baru)
    pool_empty = _StubCorePool(None)
    res_explan_empty = asyncio.run(
        tangani_kueri_eksplanatori(pool_empty, 99, "ini data apa?", 1, "TST_01", 0.0)
    )
    assert res_explan_empty["is_conversational_text"] is True
    assert "Belum ada data tabel" in res_explan_empty["ringkasan"]


def test_conversational_question_detection():
    from app.services.vanna_engine import _is_conversational_question
    assert _is_conversational_question("halo") is True
    assert _is_conversational_question("selamat pagi") is True
    assert _is_conversational_question("apa itu PKB?") is True
    assert _is_conversational_question("apa arti SPK?") is True
    assert _is_conversational_question("apa bedanya norangka dan nopolisi?") is True
    assert _is_conversational_question("kamu bisa apa saja?") is True
    assert _is_conversational_question("terima kasih") is True
    assert _is_conversational_question("makasih banyak") is True
    assert _is_conversational_question("mantap keren") is True

    # Data queries must return False
    assert _is_conversational_question("berapa total penjualan tahun 2025?") is False
    assert _is_conversational_question("tampilkan 5 mobil terlaris") is False
    assert _is_conversational_question("sisa stok saat ini") is False
    assert _is_conversational_question("tampilkan 5 mobil terlaris dan 5 pelanggan teratas") is False


def test_tangani_kueri_percakapan_fallback():
    import asyncio
    from app.services.vanna_engine import tangani_kueri_percakapan
    pool = _StubCorePool()

    res_pkb = asyncio.run(
        tangani_kueri_percakapan(pool, 1, "apa itu PKB?", 1, "TST_01", 0.0)
    )
    assert res_pkb["source"] == "conversational"
    assert res_pkb["is_conversational_text"] is True
    assert res_pkb["sql"] == ""
    assert res_pkb["rows"] == []
    assert "Perintah Kerja Bengkel" in res_pkb["ringkasan"]
    assert len(res_pkb["saran"]) >= 3

    res_halo = asyncio.run(
        tangani_kueri_percakapan(pool, 1, "halo", 1, "TST_01", 0.0)
    )
    assert res_halo["source"] == "conversational"
    assert res_halo["is_conversational_text"] is True
    assert "Selamat datang" in res_halo["ringkasan"]


def test_vanna_cek_apakah_minta_rincian_terpisah_window_sql():
    from app.services.vanna_engine import cek_apakah_minta_rincian_terpisah
    res = cek_apakah_minta_rincian_terpisah("tampilkan rincian transaksi 2023 dan 2024 terpisah", inherited_topic="penjualan")
    assert res is not None
    assert res["category"] == "rincian_terpisah"
    assert len(res["domains"]) == 2
    sql_1 = res["domains"][0]["sql"]
    sql_2 = res["domains"][1]["sql"]

    # Verifikasi keberadaan SQL Window Functions
    assert "COUNT(*) OVER() AS total_transaksi_tahun" in sql_1
    assert "SUM(hjakhir) OVER() AS total_omzet_tahun" in sql_1
    assert "LIMIT 50" in sql_1
    assert "COUNT(*) OVER() AS total_transaksi_tahun" in sql_2
    assert "SUM(hjakhir) OVER() AS total_omzet_tahun" in sql_2
    assert "LIMIT 50" in sql_2


def test_explicit_keyword_override():
    from app.services.vanna_engine import (
        deteksi_topik_eksplisit,
        _deteksi_kueri_komparasi_periode,
        cek_apakah_minta_rincian_terpisah,
    )

    # 1. Deteksi kata kunci eksplisit langsung
    assert deteksi_topik_eksplisit("Bandingkan servis 2023 vs 2024") == "servis"
    assert deteksi_topik_eksplisit("Bagaimana pengadaan unit tahun 2024?") == "pembelian"
    assert deteksi_topik_eksplisit("Penjualan mobil avanza 2024") == "penjualan"
    assert deteksi_topik_eksplisit("Cek data suku cadang 2025") == "sparepart"
    assert deteksi_topik_eksplisit("Bagaimana dengan performa tahun 2024?") is None

    # 1.1 Pencegahan False Positive (Konteks CS & Substring non-otomotif)
    assert deteksi_topik_eksplisit("Bagaimana cara menghubungi customer service?") is None
    assert deteksi_topik_eksplisit("Tingkat kepuasan servis pelanggan") is None
    assert deteksi_topik_eksplisit("Berapa mobil yang diservis di bengkel?") == "servis"
    assert deteksi_topik_eksplisit("Berapa orang yang berpartisipasi dalam acara?") is None
    assert deteksi_topik_eksplisit("Two network managers wonderful") is None
    assert deteksi_topik_eksplisit("Beliau adalah kepala cabang") is None

    # 2. Kata kunci eksplisit mengalahkan (100% override) inherited_topic penjualan
    comp = _deteksi_kueri_komparasi_periode(
        "Bandingkan servis tahun 2023 vs 2024", inherited_topic="penjualan"
    )
    assert comp is not None
    assert comp["subject"] == "servis"

    # 3. Kata kunci eksplisit mengalahkan inherited_topic pembelian pada rincian terpisah
    rincian = cek_apakah_minta_rincian_terpisah(
        "Tampilkan rincian servis 2023 dan 2024 terpisah", inherited_topic="penjualan"
    )
    assert rincian is not None
    assert rincian["topic"] == "servis"
    assert rincian["table"] == "srvt_wo"


def test_graceful_fallback_allowed_tables():
    from app.services.vanna_engine import (
        susun_kueri_komparasi_deterministik,
        cek_apakah_minta_rincian_terpisah,
    )

    comp_info = {
        "periods": [2023, 2024],
        "subject": "penjualan",
    }

    # Jika tabel ada di allowed_tables -> query dihasilkan
    sql_ok = susun_kueri_komparasi_deterministik(
        comp_info, "bandingkan penjualan 2023 vs 2024",
        allowed_tables={"untt_penjualan", "other_table"}
    )
    assert sql_ok is not None
    assert "FROM untt_penjualan" in sql_ok

    # Jika tabel TIDAK ADA di allowed_tables -> Graceful fallback ke None (LLM)
    sql_fallback = susun_kueri_komparasi_deterministik(
        comp_info, "bandingkan penjualan 2023 vs 2024",
        allowed_tables={"srvt_wo", "some_custom_table"}
    )
    assert sql_fallback is None

    # Begitu pula untuk rincian terpisah
    rincian_ok = cek_apakah_minta_rincian_terpisah(
        "tampilkan rincian servis 2023 dan 2024 terpisah",
        allowed_tables={"srvt_wo"}
    )
    assert rincian_ok is not None
    assert rincian_ok["table"] == "srvt_wo"

    rincian_fallback = cek_apakah_minta_rincian_terpisah(
        "tampilkan rincian servis 2023 dan 2024 terpisah",
        allowed_tables={"untt_penjualan"}
    )
    assert rincian_fallback is None


def test_validasi_readonly_ast_vanna():
    import pytest
    from app.services.vanna_engine import validasi_readonly_ast_vanna
    from app.services.sql_guard import SqlGuardError

    # Query aman SELECT / WITH harus lolos
    validasi_readonly_ast_vanna("SELECT * FROM untt_penjualan WHERE NOT COALESCE(batal, FALSE)")
    validasi_readonly_ast_vanna("WITH thn AS (SELECT 2024 AS yr) SELECT * FROM untt_penjualan, thn")
    validasi_readonly_ast_vanna("SELECT nomor FROM untt_penjualan UNION SELECT nomor FROM untt_pembelian")

    # Dilarang: Operasi manipulasi / DDL berbahaya
    with pytest.raises(SqlGuardError):
        validasi_readonly_ast_vanna("DROP TABLE untt_penjualan")

    with pytest.raises(SqlGuardError):
        validasi_readonly_ast_vanna("DELETE FROM untt_penjualan WHERE id = 1")

    with pytest.raises(SqlGuardError):
        validasi_readonly_ast_vanna("UPDATE untt_penjualan SET hjakhir = 0")

    with pytest.raises(SqlGuardError):
        validasi_readonly_ast_vanna("INSERT INTO untt_penjualan (nomor) VALUES ('123')")

    with pytest.raises(SqlGuardError):
        validasi_readonly_ast_vanna("SELECT * FROM untt_penjualan; DROP TABLE untt_penjualan;")

    with pytest.raises(SqlGuardError):
        validasi_readonly_ast_vanna("SELECT * INTO new_penjualan FROM untt_penjualan")

    with pytest.raises(SqlGuardError):
        validasi_readonly_ast_vanna("SELECT pg_sleep(10)")


def test_zero_cross_session_bleed():
    import asyncio
    from unittest.mock import AsyncMock
    from app.services.vanna_engine import (
        ambil_konteks_percakapan_aktif,
        deteksi_topik_riwayat_percakapan,
    )

    # Mock database pool dengan data berbeda per conversation_id
    mock_pool = AsyncMock()

    conv_messages = {
        101: [
            {"role": "user", "content": "Berapa total servis dan wo bengkel tahun 2023?"},
            {"role": "assistant", "content": '{"status": "success", "ringkasan": "Total servis 500 unit"}'},
        ],
        202: [
            {"role": "user", "content": "Berapa omzet penjualan unit tahun 2024?"},
            {"role": "assistant", "content": '{"status": "success", "ringkasan": "Total penjualan 1.2M"}'},
        ],
    }

    async def mock_fetch(sql, *params):
        conv_id = params[0]
        return conv_messages.get(conv_id, [])

    async def mock_fetchval(sql, *params):
        conv_id = params[0]
        if conv_id == 101:
            return "Performa Servis Bengkel"
        elif conv_id == 202:
            return "Performa Penjualan Dealer"
        return None

    mock_pool.fetch.side_effect = mock_fetch
    mock_pool.fetchval.side_effect = mock_fetchval

    async def run_parallel_sessions():
        # Eksekusi sesi 101 dan 202 secara paralel bersamaan
        res_101_ctx, res_202_ctx, res_101_topik, res_202_topik = await asyncio.gather(
            ambil_konteks_percakapan_aktif(mock_pool, 101),
            ambil_konteks_percakapan_aktif(mock_pool, 202),
            deteksi_topik_riwayat_percakapan(mock_pool, 101),
            deteksi_topik_riwayat_percakapan(mock_pool, 202),
        )
        return res_101_ctx, res_202_ctx, res_101_topik, res_202_topik

    res_101_ctx, res_202_ctx, res_101_topik, res_202_topik = asyncio.run(run_parallel_sessions())

    # Verifikasi sesi 101 murni 'servis', sesi 202 murni 'penjualan' — zero bleed
    assert res_101_topik == "servis"
    assert res_202_topik == "penjualan"
    assert res_101_ctx["topic"] == "servis"
    assert res_202_ctx["topic"] == "penjualan"
    assert res_101_ctx["year"] == 2023
    assert res_202_ctx["year"] == 2024


@pytest.mark.integration
def test_zero_cross_session_bleed_real_db():
    """Integrasi Database Nyata: Membuktikan WHERE conversation_id = $1
    menjamin zero cross-session bleed secara nyata di PostgreSQL.
    """
    import asyncio
    import pytest
    from app.core.database import get_core_pool, close_core_pool
    from app.services.vanna_engine import ambil_konteks_percakapan_aktif, deteksi_topik_riwayat_percakapan

    async def _run():
        try:
            pool = await get_core_pool()
        except Exception:
            pytest.skip("PostgreSQL Core Docker (port 5433) tidak aktif, lewati integrasi DB.")
            return

        # 1. Buat 2 sesi percakapan nyata di database core
        c1 = await pool.fetchval(
            "INSERT INTO conversations (user_id, branch_code, title) VALUES (1, 'TST_01', 'Test Sesi Servis Integrasi') RETURNING id"
        )
        c2 = await pool.fetchval(
            "INSERT INTO conversations (user_id, branch_code, title) VALUES (1, 'TST_01', 'Test Sesi Penjualan Integrasi') RETURNING id"
        )

        try:
            # 2. Masukkan pesan terpisah
            await pool.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES ($1, 'user', 'Berapa total servis dan wo bengkel tahun 2023?')",
                c1
            )
            await pool.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES ($1, 'user', 'Berapa omzet penjualan mobil tahun 2024?')",
                c2
            )

            # 3. Eksekusi paralel membaca dari PostgreSQL nyata
            r1_ctx, r2_ctx, r1_topik, r2_topik = await asyncio.gather(
                ambil_konteks_percakapan_aktif(pool, c1),
                ambil_konteks_percakapan_aktif(pool, c2),
                deteksi_topik_riwayat_percakapan(pool, c1),
                deteksi_topik_riwayat_percakapan(pool, c2),
            )

            # 4. Verifikasi isolasi mutlak
            assert r1_topik == "servis"
            assert r2_topik == "penjualan"
            assert r1_ctx["topic"] == "servis"
            assert r2_ctx["topic"] == "penjualan"
            assert r1_ctx["year"] == 2023
            assert r2_ctx["year"] == 2024

        finally:
            # 5. Pembersihan data uji (cleanup)
            await pool.execute("DELETE FROM messages WHERE conversation_id IN ($1, $2)", c1, c2)
            await pool.execute("DELETE FROM conversations WHERE id IN ($1, $2)", c1, c2)

    asyncio.run(_run())










