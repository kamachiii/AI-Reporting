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


def test_ekstrak_periode_waktu_3_dan_4_tahun():
    from app.services.fanout_engine import _ekstrak_periode_waktu
    res_3 = _ekstrak_periode_waktu("sekarang coba bandingkan 2020 vs 2021 vs 2022")
    assert res_3 == ["2020", "2021", "2022"]

    res_4 = _ekstrak_periode_waktu("tampilkan rincian transaksi 2020, 2021, 2022, dan 2023 terpisah")
    assert res_4 == ["2020", "2021", "2022", "2023"]


def test_cek_apakah_minta_rincian_terpisah_3_dan_4_tahun():
    # Fanout engine multi-periode
    res = cek_apakah_minta_rincian_terpisah("Tampilkan rincian transaksi 2020, 2021, dan 2022 secara terpisah")
    assert res is not None
    assert len(res["domains"]) == 3
    assert res["domains"][0]["id"] == "periode_2020"
    assert res["domains"][1]["id"] == "periode_2021"
    assert res["domains"][2]["id"] == "periode_2022"

    # Vanna engine multi-periode dengan Window Functions
    from app.services.vanna_engine import cek_apakah_minta_rincian_terpisah as vanna_rincian
    res_vanna = vanna_rincian("Tampilkan rincian transaksi 2020, 2021, 2022, 2023 terpisah", inherited_topic="penjualan")
    assert res_vanna is not None
    assert len(res_vanna["domains"]) == 4
    for idx, yr in enumerate(["2020", "2021", "2022", "2023"]):
        d = res_vanna["domains"][idx]
        assert d["id"] == f"thn_{yr}"
        assert f"Rincian Tahun {yr}" in d["title"]
        assert f"EXTRACT(YEAR FROM tanggal) = {yr}" in d["sql"]
        assert "COUNT(*) OVER() AS total_transaksi_tahun" in d["sql"]
        assert "LIMIT 50" in d["sql"]


def test_format_ringkasan_otomatis_variasi_kolom_tahun():
    from app.services.vanna_engine import _format_ringkasan_otomatis
    columns = ["tahun_invoice", "unit_terjual", "total_omzet"]
    rows = [
        [2020, 870, 173565000000],
        [2021, 777, 155011500000],
        [2022, 888, 177156000000]
    ]
    summary = _format_ringkasan_otomatis(rows, columns, "sekarang coba bandingkan 2020 vs 2021 vs 2022")
    assert "Perbandingan per tahun:" in summary
    assert "Tahun 2020: 870 unit (total Rp 173,56 Miliar)" in summary
    assert "Tahun 2021: 777 unit (total Rp 155,01 Miliar)" in summary
    assert "Tahun 2022: 888 unit (total Rp 177,16 Miliar)" in summary
