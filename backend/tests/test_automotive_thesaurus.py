"""Test suite untuk Smart Automotive Domain Thesaurus & Semantic RAG Injection."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.automotive_thesaurus import (
    deteksi_konteks_domain,
    susun_instruksi_domain,
    ambil_semua_aturan_thesaurus,
    AUTOMOTIVE_DOMAIN_RULES,
)
from app.services.vanna_pgvector import (
    cari_konteks_pgvector,
    injeksi_thesaurus_ke_pgvector,
)


def test_deteksi_konteks_penjualan_unit():
    """Menguji deteksi istilah slang omzet dan penjualan unit mobil."""
    res = deteksi_konteks_domain("berapa total omzet penjualan mobil tahun 2025?")
    categories = [r["category"] for r in res]
    assert "penjualan_unit" in categories
    assert any("untt_penjualan" in r["primary_tables"] for r in res)


def test_deteksi_konteks_servis_dan_wo():
    """Menguji deteksi istilah bengkel, work order, dan mekanik."""
    res = deteksi_konteks_domain("tampilkan daftar WO servis bulan ini beserta mekanik")
    categories = [r["category"] for r in res]
    assert "servis_bengkel" in categories
    assert any("srvt_wo" in r["primary_tables"] for r in res)


def test_deteksi_konteks_sparepart():
    """Menguji deteksi suku cadang dan inventori gudang."""
    res = deteksi_konteks_domain("apakah stok sparepart oli masih tersedia di gudang?")
    categories = [r["category"] for r in res]
    assert "suku_cadang_inventori" in categories
    assert any("invt_item" in r["primary_tables"] for r in res)


def test_deteksi_konteks_customer_dan_pelanggan():
    """Menguji deteksi entitas customer dan loyalitas pelanggan."""
    res = deteksi_konteks_domain("siapa 5 top customer dengan transaksi terbanyak?")
    categories = [r["category"] for r in res]
    assert "pelanggan_customer" in categories
    assert any("glbm_customer" in r["primary_tables"] for r in res)


def test_susun_instruksi_domain():
    """Menguji perakitan teks panduan bisnis domain otomotif."""
    rules = deteksi_konteks_domain("omzet penjualan")
    instruksi = susun_instruksi_domain(rules)
    assert "=== DOMAIN BUSINESS RULES & SCHEMA CONVENTIONS (AUTOMOTIVE DMS) ===" in instruksi
    assert "untt_penjualan.batal = false AND untt_penjualan.retur = false" in instruksi
    assert "SUM(untt_penjualan.hjakhir)" in instruksi


def test_ambil_semua_aturan_thesaurus():
    """Menguji pengambilan seluruh kamus aturan untuk vektorisasi."""
    entries = ambil_semua_aturan_thesaurus()
    assert len(entries) == len(AUTOMOTIVE_DOMAIN_RULES)
    for entry in entries:
        assert "Domain: Automotive DMS" in entry["content"]
        assert "Rules:" in entry["content"]
        assert isinstance(entry["tables"], list)


@pytest.mark.anyio
async def test_cari_konteks_pgvector_menyertakan_aturan_domain():
    """Menguji apakah pencarian pgvector menyertakan domain guidelines secara otomatis."""
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[
        {"content": "Table untt_penjualan (nomor varchar, hjakhir numeric)", "item_type": "ddl"}
    ])
    mock_pool.fetchrow = AsyncMock(return_value=None)

    with patch("app.services.vanna_pgvector.hitung_embedding", AsyncMock(return_value=[0.1] * 384)):
        context, tables = await cari_konteks_pgvector(mock_pool, "TST_01", "berapa omzet tahun 2025?")

        assert "=== DOMAIN BUSINESS RULES & SCHEMA CONVENTIONS (AUTOMOTIVE DMS) ===" in context
        assert "untt_penjualan" in tables


@pytest.mark.anyio
async def test_injeksi_thesaurus_ke_pgvector():
    """Menguji fungsi vektorisasi massal aturan kamus otomotif ke database core."""
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value={"id": 999})

    with patch("app.services.vanna_pgvector.hitung_embedding", AsyncMock(return_value=[0.1] * 384)):
        count = await injeksi_thesaurus_ke_pgvector(mock_pool)
        assert count == len(AUTOMOTIVE_DOMAIN_RULES)
        assert mock_pool.fetchrow.call_count == len(AUTOMOTIVE_DOMAIN_RULES)
