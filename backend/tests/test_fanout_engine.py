"""test_fanout_engine.py — Unit test untuk Mesin Query Fan-Out 3S Dealer Otomotif."""

import pytest
from app.services.fanout_engine import (
    cek_apakah_perlu_fanout,
    susun_multi_sql_prompt,
    ekstrak_multi_sql,
    susun_ringkasan_eksekutif_multi,
    cek_apakah_perlu_komparasi,
    susun_tab_komparasi_divisi,
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
    assert "Rp 452,8 Miliar" in summary
    assert "Rp 18,4 Miliar" in summary
    assert "Rp 26,1 Miliar" in summary


def test_cek_apakah_perlu_komparasi():
    assert cek_apakah_perlu_komparasi("Bandingkan performa antar divisi tahun ini") is True
    assert cek_apakah_perlu_komparasi("Komparasi omzet unit vs servis") is True
    assert cek_apakah_perlu_komparasi("Berapa kontribusi masing-masing divisi?") is True
    assert cek_apakah_perlu_komparasi("Berapa total penjualan tahun 2025?") is False


def test_susun_tab_komparasi_divisi():
    domain_results = [
        {
            "id": "unit",
            "title": "Unit Kendaraan",
            "columns": ["bulan", "jumlah_unit_terjual", "total_omzet_unit"],
            "rows": [["2026-06", 3, 900_000_000]],
            "row_count": 1,
            "raw_records": [{"bulan": "2026-06", "jumlah_unit_terjual": 3, "total_omzet_unit": 900_000_000}],
            "sql": "SELECT ... untt_penjualan",
            "error": None
        },
        {
            "id": "service",
            "title": "Jasa Servis Bengkel",
            "columns": ["bulan", "jumlah_pkb", "total_pendapatan_jasa"],
            "rows": [["2026-06", 10, 100_000_000]],
            "row_count": 1,
            "raw_records": [{"bulan": "2026-06", "jumlah_pkb": 10, "total_pendapatan_jasa": 100_000_000}],
            "sql": "SELECT ... srvt_wo",
            "error": None
        }
    ]
    komparasi = susun_tab_komparasi_divisi(domain_results, "Bandingkan performa antar divisi")
    assert komparasi is not None
    assert komparasi["id"] == "komparasi"
    assert komparasi["title"] in ("Ringkasan Komparasi", "Komparasi Antar Divisi")
    assert "kategori" in komparasi["columns"] or "divisi" in komparasi["columns"]
    assert "total_omzet" in komparasi["columns"]
    assert "kontribusi_omzet" in komparasi["columns"]
    assert len(komparasi["rows"]) == 2
    # Cek kontribusi persentase
    unit_row = next(r for r in komparasi["rows"] if r[0] == "Unit Kendaraan")
    assert unit_row[1] == 3
    assert unit_row[2] == 900_000_000
    assert unit_row[3] == "90,0%"

    serv_row = next(r for r in komparasi["rows"] if r[0] == "Jasa Servis Bengkel")
    assert serv_row[1] == 10
    assert serv_row[2] == 100_000_000
    assert serv_row[3] == "10,0%"


def test_cek_apakah_minta_multi_query_dan_single():
    from app.services.fanout_engine import cek_apakah_minta_multi_query
    # Kueri multi-laporan eksplisit
    multi_res = cek_apakah_minta_multi_query("tampilkan 5 mobil terlaris dan 5 pelanggan teratas")
    assert multi_res is not None
    assert len(multi_res["domains"]) == 2
    titles = [d["title"] for d in multi_res["domains"]]
    assert "5 Mobil Terlaris" in titles
    assert "5 Pelanggan Teratas" in titles

    # Kueri data tunggal tidak boleh terpicu multi-query
    assert cek_apakah_minta_multi_query("berapa total penjualan tahun 2025?") is None
    assert cek_apakah_minta_multi_query("tampilkan sisa stok saat ini") is None
    assert cek_apakah_minta_multi_query("penjualan mobil honda dan toyota") is None



def test_smart_context_note_tahun_berjalan():
    domain_results = [
        {
            "title": "Unit Kendaraan",
            "columns": ["bulan", "jumlah_unit", "omzet"],
            "rows": [["2026-06", 3, 944900000]],
            "row_count": 1
        }
    ]
    summary = susun_ringkasan_eksekutif_multi(domain_results, "Bandingkan performa antar divisi tahun ini")
    assert "Catatan Analitik" in summary
    assert "2026" in summary
    assert "2025 atau 2024" in summary


def test_column_classification_rules():
    from app.services.fanout_engine import _is_column_qty, _is_column_money
    assert _is_column_qty("volume_unit_terjual") is True
    assert _is_column_money("volume_unit_terjual") is False

    assert _is_column_qty("omzet_penjualan_unit") is False
    assert _is_column_money("omzet_penjualan_unit") is True

    assert _is_column_qty("kuantiti_part_terjual") is True
    assert _is_column_money("kuantiti_part_terjual") is False

    assert _is_column_qty("total_penjualan_part") is False
    assert _is_column_money("total_penjualan_part") is True

    assert _is_column_qty("jumlah_wo_pkb") is True
    assert _is_column_money("jumlah_wo_pkb") is False


def test_multitab_spareparts_and_grammar_cleaning():
    from app.services.fanout_engine import susun_ringkasan_eksekutif_multi
    domain_results = [
        {
            "id": "unit",
            "title": "Unit Kendaraan",
            "columns": ["jumlah_unit_terjual", "total_omzet_penjualan"],
            "rows": [[350, 69825000000]],
            "raw_records": [{"jumlah_unit_terjual": 350, "total_omzet_penjualan": 69825000000}]
        },
        {
            "id": "servis",
            "title": "Jasa Servis Bengkel",
            "columns": ["jumlah_wo_pkb", "total_pendapatan_servis"],
            "rows": [[13313, 22500000000]],
            "raw_records": [{"jumlah_wo_pkb": 13313, "total_pendapatan_servis": 22500000000}]
        },
        {
            "id": "part",
            "title": "Suku Cadang & Sparepart",
            "columns": ["kuantiti_part_terjual", "total_penjualan_part"],
            "rows": [[117790, 42180000000]],
            "raw_records": [{"kuantiti_part_terjual": 117790, "total_penjualan_part": 42180000000}]
        }
    ]
    summary = susun_ringkasan_eksekutif_multi(domain_results, "bagaimana performa transaksi tahun 2025")
    assert "Rp 117.790" not in summary
    assert "117.790 part terjual" in summary
    assert "350 unit terjual" in summary
    assert "13.313 PKB servis" in summary
    assert "Rp 42,18 Miliar" in summary


def test_susun_tab_komparasi_single_domain_rejected():
    from app.services.fanout_engine import susun_tab_komparasi_divisi
    domain_results = [
        {
            "id": "unit",
            "title": "Unit Kendaraan",
            "columns": ["tahun", "total_unit", "total_omzet"],
            "rows": [[2024, 947, 225713358000]],
            "raw_records": [{"tahun": 2024, "total_unit": 947, "total_omzet": 225713358000}]
        }
    ]
    # Single division should NOT produce a "Komparasi Antar Divisi"
    assert susun_tab_komparasi_divisi(domain_results, "Bandingkan pembelian tahun 2024 vs 2025") is None


def test_susun_ringkasan_rincian_window_aggregation():
    from app.services.fanout_engine import susun_ringkasan_eksekutif_multi
    domain_results = [
        {
            "id": "thn_2023",
            "title": "Rincian Tahun 2023",
            "columns": ["nomor", "tanggal", "nomor_pesanan", "norangka", "hjunit", "diskon", "hjakhir"],
            "rows": [["INV01", "2023-01-01", "PO01", "FRAME01", 165000000, 0, 165000000]] * 50,
            "row_count": 50,
            "total_full_count": 1032,
            "total_full_money": 205884000000.0,
            "raw_records": [{"nomor": f"INV{i}", "hjakhir": 165000000} for i in range(50)],
        },
        {
            "id": "thn_2024",
            "title": "Rincian Tahun 2024",
            "columns": ["nomor", "tanggal", "nomor_pesanan", "norangka", "hjunit", "diskon", "hjakhir"],
            "rows": [["INV02", "2024-01-01", "PO02", "FRAME02", 175000000, 0, 175000000]] * 50,
            "row_count": 50,
            "total_full_count": 952,
            "total_full_money": 189920000000.0,
            "raw_records": [{"nomor": f"INV{i}", "hjakhir": 175000000} for i in range(50)],
        }
    ]
    summary = susun_ringkasan_eksekutif_multi(domain_results, "tampilkan rincian transaksi 2023 dan 2024 terpisah")
    assert "Menampilkan pratinjau 50 transaksi terbaru dari total 1.032 transaksi" in summary
    assert "Total Omzet: Rp 205,88 Miliar" in summary
    assert "Menampilkan pratinjau 50 transaksi terbaru dari total 952 transaksi" in summary
    assert "Total Omzet: Rp 189,92 Miliar" in summary



