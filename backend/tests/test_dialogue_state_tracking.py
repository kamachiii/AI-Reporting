import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from app.services.vanna_engine import (
    is_action_confirmation_phrase,
    evaluasi_state_percakapan,
    _periksa_integritas_output_percakapan,
    _is_explanatory_question,
    tangani_kueri_eksplanatori,
)


def test_action_confirmation_phrases():
    # Positif (persetujuan / delegasi tindakan)
    assert is_action_confirmation_phrase("atur aja") is True
    assert is_action_confirmation_phrase("hmm yaudah atur aja..") is True
    assert is_action_confirmation_phrase("kamu yang atur") is True
    assert is_action_confirmation_phrase("terserah kamu") is True
    assert is_action_confirmation_phrase("lanjutkan") is True
    assert is_action_confirmation_phrase("lanjut") is True
    assert is_action_confirmation_phrase("gas") is True
    assert is_action_confirmation_phrase("gaskan") is True
    assert is_action_confirmation_phrase("proses ya") is True
    assert is_action_confirmation_phrase("pilihin aja") is True

    # Negatif (bukan frase konfirmasi)
    assert is_action_confirmation_phrase("tampilkan 5 mobil terlaris") is False
    assert is_action_confirmation_phrase("loh grafiknya mana?") is False
    assert is_action_confirmation_phrase("halo selamat pagi") is False
    assert is_action_confirmation_phrase("berapa omzet bulan ini?") is False


def test_mechanical_output_guard_detects_and_strips_fake_tables():
    # 1. Teks berisi halusinasi tabel numerik (seperti insiden turn #16)
    fake_text = (
        "Berikut ringkasan data keuangan:\n\n"
        "| No | Bulan | Penerimaan |\n"
        "| :--- | :--- | :--- |\n"
        "| 1 | Januari 2025 | Rp 12.400.000.000 |\n"
        "| 2 | Februari 2025 | Rp 14.200.000.000 |\n\n"
        "Grafik interaktif sudah disiapkan di panel kanan."
    )
    is_valid, cleaned = _periksa_integritas_output_percakapan(fake_text)
    assert is_valid is False
    # Tabel numerik dan klaim fiktif harus dibersihkan
    assert "Rp 12.400.000.000" not in cleaned
    assert "Grafik interaktif sudah disiapkan" not in cleaned

    # 2. Teks berisi peta skema database yang valid (bukan transaksi fiktif)
    valid_schema_text = (
        "Database memiliki tabel-tabel berikut:\n\n"
        "| Kategori | Jumlah | Isinya |\n"
        "| :--- | :--- | :--- |\n"
        "| `vw_` | 706 | View laporan |\n"
        "| `srvt` | 1080 | Servis |\n"
    )
    is_valid_schema, cleaned_schema = _periksa_integritas_output_percakapan(valid_schema_text)
    assert is_valid_schema is True
    assert "706" in cleaned_schema


@pytest.mark.anyio
async def test_evaluasi_state_percakapan_accepts_default_action():
    mock_pool = AsyncMock()
    mock_proposal = {
        "intent": "financial_analysis",
        "topic": "keuangan",
        "status": "awaiting_confirmation",
        "options": [
            {
                "id": "kasir_bulanan",
                "label": "Tren Pembayaran Kasir Bulanan 2025",
                "query": "Tampilkan total pembayaran kasir per bulan tahun 2025 beserta grafik trennya",
                "keywords": ["kasir", "bulanan", "tren"],
            },
            {
                "id": "piutang_customer",
                "label": "Analisis Piutang Customer",
                "query": "Siapa saja 10 customer dengan saldo piutang tertinggi yang belum lunas?",
                "keywords": ["piutang", "tunggakan"],
            },
        ],
        "default_action": {
            "id": "kasir_bulanan",
            "query": "Tampilkan total pembayaran kasir per bulan tahun 2025 beserta grafik trennya",
        },
    }

    mock_row = {
        "id": 999,
        "content": json.dumps({"source": "conversational", "pending_proposal": mock_proposal}),
    }
    mock_pool.fetchrow.return_value = mock_row

    # Kasus: user menjawab "hmm yaudah atur aja.."
    resolved_q, accepted, chosen = await evaluasi_state_percakapan(mock_pool, 79, "hmm yaudah atur aja..")
    assert accepted is True
    assert resolved_q == "Tampilkan total pembayaran kasir per bulan tahun 2025 beserta grafik trennya"
    assert chosen["id"] == "kasir_bulanan"
    # Pastikan row diupdate
    mock_pool.execute.assert_called_once()


@pytest.mark.anyio
async def test_evaluasi_state_percakapan_selects_specific_option():
    mock_pool = AsyncMock()
    mock_proposal = {
        "intent": "financial_analysis",
        "topic": "keuangan",
        "status": "awaiting_confirmation",
        "options": [
            {
                "id": "kasir_bulanan",
                "label": "Tren Kasir",
                "query": "Tampilkan kasir bulanan",
                "keywords": ["kasir"],
            },
            {
                "id": "piutang_customer",
                "label": "Piutang Customer",
                "query": "Siapa saja 10 customer piutang tertinggi?",
                "keywords": ["piutang"],
            },
        ],
        "default_action": {
            "id": "kasir_bulanan",
            "query": "Tampilkan kasir bulanan",
        },
    }
    mock_row = {
        "id": 999,
        "content": json.dumps({"source": "conversational", "pending_proposal": mock_proposal}),
    }
    mock_pool.fetchrow.return_value = mock_row

    # Kasus: user memilih opsi 2
    resolved_q, accepted, chosen = await evaluasi_state_percakapan(mock_pool, 79, "opsi 2")
    assert accepted is True
    assert resolved_q == "Siapa saja 10 customer piutang tertinggi?"
    assert chosen["id"] == "piutang_customer"


@pytest.mark.anyio
async def test_tangani_kueri_eksplanatori_graphic_inquiry():
    mock_pool = AsyncMock()
    # Mock percakapan sebelumnya belum ada row data (hanya proposal percakapan)
    mock_row = {
        "content": json.dumps({
            "source": "conversational",
            "ringkasan": "Silakan pilih modul keuangan.",
            "rows": [],
            "pending_proposal": {
                "options": [
                    {"query": "Tampilkan pembayaran kasir 2025"}
                ]
            }
        })
    }
    mock_pool.fetchrow.return_value = mock_row
    mock_pool.fetchval.return_value = 79

    res = await tangani_kueri_eksplanatori(
        core_pool=mock_pool,
        conversation_id=79,
        question="loh grafiknya mana?",
        user_id=1,
        branch_code="TST_01",
        t0=0.0
    )

    assert res["status"] == "success"
    # Penjelasan harus jujur bahwa grafik aktif setelah kueri SQL dieksekusi
    assert "Visualisasi grafik interaktif" in res["ringkasan"]
    assert "belum ditarik" in res["ringkasan"]
    assert "Tampilkan pembayaran kasir 2025" in res["saran"]


@pytest.mark.anyio
async def test_tangani_kueri_eksplanatori_graphic_inquiry_when_rows_exist():
    mock_pool = AsyncMock()
    # Mock percakapan sebelumnya SUDAH MEMILIKI 11 baris data transaksi nyata
    mock_row = {
        "content": json.dumps({
            "source": "vanna",
            "question": "Tampilkan tren penjualan unit dan total omzet per bulan tahun 2025",
            "columns": ["bulan", "unit_terjual", "total_omzet"],
            "rows": [["2025-01", 12, 100000000], ["2025-02", 15, 120000000]],
            "row_count": 2,
        })
    }
    mock_pool.fetchrow.return_value = mock_row
    mock_pool.fetchval.return_value = 83

    res = await tangani_kueri_eksplanatori(
        core_pool=mock_pool,
        conversation_id=83,
        question="loh grafiknya mana?",
        user_id=1,
        branch_code="TST_01",
        t0=0.0
    )

    assert res["status"] == "success"
    # Penjelasan HARUS memandu user ke toggle tab Grafik pada kartu laporan di atas,
    # BUKAN menjelaskan fungsi kolom tabel!
    assert "sudah tersedia langsung pada kartu laporan di atas" in res["ringkasan"]
    assert "toggle tab **Grafik**" in res["ringkasan"]
    assert "Tabel di atas menampilkan" not in res["ringkasan"]


@pytest.mark.anyio
async def test_evaluasi_state_percakapan_cancellation():
    mock_pool = AsyncMock()
    mock_proposal = {
        "intent": "financial_analysis",
        "topic": "keuangan",
        "status": "awaiting_confirmation",
        "options": [
            {"id": "kasir_bulanan", "query": "Tampilkan kasir bulanan", "keywords": ["kasir"]},
        ],
        "default_action": {"id": "kasir_bulanan", "query": "Tampilkan kasir bulanan"},
    }
    mock_row = {
        "id": 100,
        "content": json.dumps({"pending_proposal": mock_proposal}),
    }
    mock_pool.fetchrow.return_value = mock_row

    resolved_q, accepted, chosen = await evaluasi_state_percakapan(mock_pool, 79, "ga jadi deh batal")
    assert accepted is False
    assert chosen is None
    assert resolved_q == "ga jadi deh batal"


@pytest.mark.anyio
async def test_evaluasi_state_percakapan_keyword():
    mock_pool = AsyncMock()
    mock_proposal = {
        "intent": "financial_analysis",
        "topic": "keuangan",
        "status": "awaiting_confirmation",
        "options": [
            {"id": "kasir_bulanan", "query": "Tampilkan kasir bulanan", "keywords": ["kasir", "bulanan"]},
            {"id": "piutang_customer", "query": "Tampilkan piutang", "keywords": ["piutang", "tunggakan"]},
        ],
        "default_action": {"id": "kasir_bulanan", "query": "Tampilkan kasir bulanan"},
    }
    mock_row = {
        "id": 101,
        "content": json.dumps({"pending_proposal": mock_proposal}),
    }
    mock_pool.fetchrow.return_value = mock_row

    resolved_q, accepted, chosen = await evaluasi_state_percakapan(mock_pool, 79, "mau cek piutang aja")
    assert accepted is True
    assert chosen["id"] == "piutang_customer"
    assert resolved_q == "Tampilkan piutang"
