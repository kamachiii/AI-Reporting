import pytest
from app.services.clarification_engine import cek_ambiguitas_pertanyaan


def test_ambiguous_penjualan():
    res = cek_ambiguitas_pertanyaan("berapa total penjualan tahun 2025")
    assert res is not None
    assert res["category"] == "penjualan"
    assert "divisi bisnis dealer" in res["message"]
    assert len(res["options"]) == 3
    labels = [opt["label"] for opt in res["options"]]
    assert "Penjualan Unit Mobil" in labels
    assert "Penjualan Sparepart / Suku Cadang" in labels
    assert "Total Gabungan (Unit & Sparepart)" in labels
    # Prompt sudah disisipkan qualifier spesifik
    prompts = [opt["prompt"] for opt in res["options"]]
    assert any("unit mobil" in p for p in prompts)
    assert any("sparepart" in p for p in prompts)


def test_specific_penjualan_unit_returns_none():
    assert cek_ambiguitas_pertanyaan("berapa total penjualan unit mobil di tahun 2025") is None
    assert cek_ambiguitas_pertanyaan("penjualan kendaraan roda empat") is None
    assert cek_ambiguitas_pertanyaan("total omzet per tipe mobil") is None


def test_specific_penjualan_part_returns_none():
    assert cek_ambiguitas_pertanyaan("berapa total penjualan sparepart di tahun 2025") is None
    assert cek_ambiguitas_pertanyaan("omzet suku cadang dan oli") is None
    assert cek_ambiguitas_pertanyaan("penjualan jasa servis bengkel") is None


def test_ambiguous_stok():
    res = cek_ambiguitas_pertanyaan("tampilkan sisa stok saat ini")
    assert res is not None
    assert res["category"] == "stok"
    assert len(res["options"]) == 2
    labels = [opt["label"] for opt in res["options"]]
    assert "Stok Unit Kendaraan" in labels
    assert "Stok Sparepart & Suku Cadang" in labels


def test_specific_stok_returns_none():
    assert cek_ambiguitas_pertanyaan("tampilkan sisa stok unit mobil") is None
    assert cek_ambiguitas_pertanyaan("persediaan suku cadang dan oli") is None


def test_ambiguous_pembelian():
    res = cek_ambiguitas_pertanyaan("rekap data pembelian tahun 2025")
    assert res is not None
    assert res["category"] == "pembelian"
    assert len(res["options"]) == 2


def test_unrelated_or_short_query_returns_none():
    assert cek_ambiguitas_pertanyaan("halo") is None
    assert cek_ambiguitas_pertanyaan("siapa nama kepala cabang") is None
    assert cek_ambiguitas_pertanyaan("") is None
