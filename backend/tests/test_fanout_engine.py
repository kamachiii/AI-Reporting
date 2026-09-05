"""test_fanout_engine.py — Unit test untuk Mesin Query Fan-Out 3S Dealer Otomotif."""

import pytest
from app.services.fanout_engine import (
    cek_apakah_perlu_fanout,
    susun_multi_sql_prompt,
    ekstrak_multi_sql,
    susun_ringkasan_eksekutif_multi,
)


def test_cek_apakah_perlu_fanout_penjualan():
    info = cek_apakah_perlu_fanout("berapa total penjualan tahun 2025?")
    assert info is not None
    assert info["category"] == "penjualan"
    assert info["mode"] == "3s"
    domain_ids = [d["id"] for d in info["domains"]]
    assert domain_ids == ["unit", "service", "part"]


def test_cek_apakah_perlu_fanout_stok():
    info = cek_apakah_perlu_fanout("tampilkan sisa stok saat ini")
    assert info is not None
    assert info["category"] == "stok"
    assert info["mode"] == "2s"
    domain_ids = [d["id"] for d in info["domains"]]
    assert domain_ids == ["stok_unit", "stok_part"]


def test_cek_apakah_perlu_fanout_qualifiers_bypass():
    # Pertanyaan spesifik harus me-return None (tidak perlu fanout)
    assert cek_apakah_perlu_fanout("berapa penjualan unit mobil di tahun 2025?") is None
    assert cek_apakah_perlu_fanout("tampilkan stok sparepart kampas rem") is None
    assert cek_apakah_perlu_fanout("siapa 5 customer terbesar?") is None


def test_susun_multi_sql_prompt():
    info = cek_apakah_perlu_fanout("berapa performa transaksi tahun 2025?")
    prompt = susun_multi_sql_prompt("berapa performa transaksi tahun 2025?", info, "DDL Context...")
    assert "unit" in prompt
    assert "service" in prompt
    assert "part" in prompt
    assert "JSON" in prompt


def test_ekstrak_multi_sql_valid_json():
    raw_output = """Here are the queries:
```json
{
  "unit": "SELECT count(*) FROM untt_penjualan WHERE batal = false;",
  "service": "SELECT sum(total_biaya) FROM womt_wo WHERE batal = false;",
  "part": "SELECT sum(total_harga) FROM womt_wopart;"
}
```
Hope this helps!"""
    res = ekstrak_multi_sql(raw_output, ["unit", "service", "part"])
    assert res["unit"] == "SELECT count(*) FROM untt_penjualan WHERE batal = false"
    assert res["service"] == "SELECT sum(total_biaya) FROM womt_wo WHERE batal = false"
    assert res["part"] == "SELECT sum(total_harga) FROM womt_wopart"


def test_ekstrak_multi_sql_fallback_regex():
    raw_output = 'Result: {"unit": "SELECT 1", "service": "SELECT 2", "part": "SELECT 3"}'
    res = ekstrak_multi_sql(raw_output, ["unit", "service", "part"])
    assert res["unit"] == "SELECT 1"
    assert res["service"] == "SELECT 2"
    assert res["part"] == "SELECT 3"


def test_susun_ringkasan_eksekutif_multi():
    domain_results = [
        {
            "title": "Unit Kendaraan",
            "columns": ["total_unit", "total_omzet"],
            "rows": [[2270, 452800000000.0]],
        },
        {
            "title": "Jasa Servis Bengkel",
            "columns": ["total_pkb", "total_pendapatan"],
            "rows": [[14200, 18400000000.0]],
        },
        {
            "title": "Suku Cadang",
            "columns": ["total_item", "total_penjualan"],
            "rows": [[48900, 26100000000.0]],
        }
    ]
    summary = susun_ringkasan_eksekutif_multi(domain_results, "performa 2025")
    assert "Unit Kendaraan" in summary
    assert "Jasa Servis Bengkel" in summary
    assert "Suku Cadang" in summary
    assert "Rp 452,8 M" in summary
    assert "Rp 18,4 M" in summary
    assert "Rp 26,1 M" in summary
