import pytest
from app.services.fanout_engine import (
    _ekstrak_dua_periode,
    cek_apakah_minta_rincian_terpisah,
    _deteksi_kueri_komparasi_periode,
)
from app.services.vanna_engine import _bersihkan_emoji_teks


def test_ekstrak_dua_periode():
    assert _ekstrak_dua_periode("bandingkan penjualan 2024 vs 2025") == ("2024", "2025")
    assert _ekstrak_dua_periode("pembelian tahun 2025 dan 2026") == ("2025", "2026")
    assert _ekstrak_dua_periode("komparasi semester 1 vs semester 2") == ("semester 1", "semester 2")
    assert _ekstrak_dua_periode("data tahun 2025 saja") is None


def test_deteksi_kueri_komparasi_periode():
    res = _deteksi_kueri_komparasi_periode("bandingkan penjualan tahun 2024 vs 2025")
    assert res is not None
    assert res["is_comparison"] is True
    assert res["p1"] == "2024"
    assert res["p2"] == "2025"
    assert res["topic"] == "penjualan"

    res_beli = _deteksi_kueri_komparasi_periode("pembelian unit 2025 dan 2026")
    assert res_beli is not None
    assert res_beli["p1"] == "2025"
    assert res_beli["p2"] == "2026"
    assert res_beli["topic"] == "pembelian"


def test_cek_apakah_minta_rincian_terpisah():
    res = cek_apakah_minta_rincian_terpisah("Tampilkan rincian transaksi penjualan tahun 2024 dan 2025 secara terpisah")
    assert res is not None
    assert res["category"] == "rincian_terpisah"
    assert res["p1"] == "2024"
    assert res["p2"] == "2025"
    assert len(res["domains"]) == 2
    assert res["domains"][0]["id"] == "periode_2024"
    assert res["domains"][0]["icon"] == "Calendar"
    assert res["domains"][1]["id"] == "periode_2025"
    assert res["domains"][1]["icon"] == "Calendar"

    # Pertanyaan biasa tidak boleh memicu rincian terpisah
    assert cek_apakah_minta_rincian_terpisah("bandingkan penjualan tahun 2024 vs 2025") is None


def test_bersihkan_emoji_teks():
    teks_dengan_emoji = "📊 Ringkasan Penjualan: Rp 1,5 M 🚀 Naik 20% ✨"
    bersih = _bersihkan_emoji_teks(teks_dengan_emoji)
    assert "📊" not in bersih
    assert "🚀" not in bersih
    assert "✨" not in bersih
    assert "Ringkasan Penjualan: Rp 1,5 M" in bersih
