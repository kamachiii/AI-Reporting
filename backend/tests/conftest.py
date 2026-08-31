"""
Konfigurasi pytest untuk backend.

Menjalankan test yang tidak butuh database:
    cd backend && .venv/Scripts/python -m pytest tests/ -v

Test yang butuh DB (integration) diberi marker @pytest.mark.integration
dan hanya jalan jika Docker Postgres hidup.
"""
import copy
import os
import sys

import pytest

# Pastikan package app bisa diimport dari root backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixture skema tenant (bentuk schema_config_json, lihat schema_introspector)
# yang mencerminkan skema dealer_dummy (seed_tenant_dummy.py) — dipakai test
# verifier (F2.3') TANPA koneksi DB nyata.
# ---------------------------------------------------------------------------
def _tabel(kolom, fks=None):
    return {
        "columns": [{"name": k, "type": t, "nullable": True, "default": None}
                    for k, t in kolom],
        "primary_key": ["id"],
        "foreign_keys": fks or [],
        "sample_rows": [],
    }


SCHEMA_CONFIG_DEALER = {
    "introspected_at": "2026-01-01T00:00:00+00:00",
    "tables": {
        "kendaraan": _tabel([
            ("id", "integer"), ("nomor_rangka", "character varying"),
            ("nomor_mesin", "character varying"), ("merek", "character varying"),
            ("model", "character varying"), ("tahun", "integer"),
            ("warna", "character varying"), ("harga_jual", "bigint"),
            ("status", "character varying"), ("tanggal_masuk", "date"),
        ]),
        "pelanggan": _tabel([
            ("id", "integer"), ("nama", "character varying"),
            ("no_telepon", "character varying"), ("email", "character varying"),
            ("alamat", "text"), ("kota", "character varying"),
            ("tanggal_daftar", "date"),
        ]),
        "penjualan": _tabel([
            ("id", "integer"), ("tanggal", "date"),
            ("pelanggan_id", "integer"), ("kendaraan_id", "integer"),
            ("harga_deal", "bigint"), ("metode_pembayaran", "character varying"),
            ("uang_muka", "bigint"), ("tenor_bulan", "integer"),
            ("nama_sales", "character varying"), ("catatan", "text"),
        ], [
            {"column": "pelanggan_id", "references_table": "pelanggan",
             "references_column": "id"},
            {"column": "kendaraan_id", "references_table": "kendaraan",
             "references_column": "id"},
        ]),
        "detail_penjualan": _tabel([
            ("id", "integer"), ("penjualan_id", "integer"),
            ("komponen", "character varying"), ("jumlah", "bigint"),
        ], [
            {"column": "penjualan_id", "references_table": "penjualan",
             "references_column": "id"},
        ]),
        "service_records": _tabel([
            ("id", "integer"), ("kendaraan_id", "integer"),
            ("pelanggan_id", "integer"), ("tanggal_service", "date"),
            ("jenis_service", "character varying"), ("biaya", "bigint"),
            ("km", "integer"), ("teknisi", "character varying"),
            ("keterangan", "text"),
        ], [
            {"column": "kendaraan_id", "references_table": "kendaraan",
             "references_column": "id"},
            {"column": "pelanggan_id", "references_table": "pelanggan",
             "references_column": "id"},
        ]),
    },
}


@pytest.fixture
def schema_config_dealer():
    """Salinan skema dealer_dummy untuk satu test (bebas dimodifikasi)."""
    return copy.deepcopy(SCHEMA_CONFIG_DEALER)
