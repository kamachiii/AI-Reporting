"""F5 — Test builder metrik dashboard (murni, tanpa DB).

Kontrak yang dikunci:
- Semua SQL single SELECT read-only berparameter ($n), tanpa literal tanggal.
- Profit unit memakai modal HP (join norangka); profit bengkel = grandtotal - discount.
- Filter cabang: daftar kosong -> semua (IS NULL ...), terisi -> ANY($n).
- deteksi_kemampuan: skema Otobitz penuh -> semua True; skema dummy
  (5 tabel) -> hanya sebagian (degradasi anggun, bukan mati total).
"""
import copy

from app.services import dashboard_metrics as dm


def _skema_otobitz():
    def tab(*kolom):
        return {"columns": [{"name": k, "type": "character varying",
                             "nullable": True, "default": None} for k in kolom],
                "primary_key": [], "foreign_keys": [], "sample_rows": []}
    return {"tables": {
        "untt_penjualan": tab("nomor", "tanggal", "norangka", "hjakhir",
                              "diskon", "batal", "retur", "kode_cabang"),
        "untt_pesanankendaraan": tab("nomor", "tanggal", "batal", "kode_bank",
                                     "kode_cabang", "jumlahpenjualan",
                                     "jumlahmatching"),
        "untt_datakendaraan": tab("norangka", "kode_tipe", "hpunit", "hpdpp",
                                  "hjakhir", "nopenjualan"),
        "untm_tipe": tab("kode", "nama"),
        "srvt_wo": tab("nomor", "tanggal", "batal", "penerima", "kode_cabang"),
        "srvt_faktur": tab("nomor", "tanggal", "batal", "grandtotal",
                           "discount", "total_jasa", "total_parts",
                           "kode_cabang"),
        "srvt_stockparts": tab("kode_parts", "stockawal", "masuk", "keluar",
                               "kode_cabang"),
        "untt_pesananaccessories": tab("nomor"),
        "srv_vw_daftarumurpiutang": tab("belumjt", "jtsampai30", "kode_cabang"),
        "srv_vw_daftarumurhutang": tab("belumjt", "jtsampai30", "kode_cabang"),
        "glbm_cabang": tab("kode", "nama"),
    }}


def test_kemampuan_otobitz_penuh():
    mampu = dm.deteksi_kemampuan(_skema_otobitz())
    assert all(mampu.values()), mampu


def test_kemampuan_dummy_sebagian(schema_config_dealer):
    mampu = dm.deteksi_kemampuan(schema_config_dealer)
    # Skema dummy tidak punya tabel Otobitz -> semua False kecuali aman
    assert mampu["spk"] is False
    assert mampu["faktur"] is False
    assert mampu["ar_aging"] is False
    assert mampu["filter_cabang"] is False


def test_sql_spk_tanpa_literal():
    sql, params = dm.sql_spk_ringkasan(dm.PROFIL_OTOBITZ, "2025-01-01",
                                       "2025-02-01", [])
    assert "2025" not in sql  # tanggal hanya via $1/$2
    assert params == ["2025-01-01", "2025-02-01", None]
    assert "batal" in sql and "outstanding" in sql


def test_sql_cabang_terisi():
    sql, params = dm.sql_penjualan_ringkasan(dm.PROFIL_OTOBITZ, "2025-01-01",
                                             "2025-02-01", ["210"])
    assert "ANY($3::text[])" in sql
    assert params[2] == ["210"]


def test_sql_unit_nilai_komponen_transparan():
    sql, _ = dm.sql_unit_nilai(dm.PROFIL_OTOBITZ, "2025-01-01",
                               "2025-02-01", [])
    assert "JOIN" in sql and "norangka" in sql
    for k in ("hpunit", "hpdpp"):
        assert k in sql
    assert "hjakhir" in sql
    # DILARANG klaim profit: tidak boleh ada kolom 'profit' hasil hitung
    assert " AS profit" not in sql


def test_sql_faktur_profit_proxy():
    sql, _ = dm.sql_faktur_ringkasan(dm.PROFIL_OTOBITZ, "2025-01-01",
                                     "2025-02-01", [])
    assert "grandtotal" in sql and "discount" in sql


def test_sql_aging_view_bucket():
    sql, params = dm.sql_ar_aging(dm.PROFIL_OTOBITZ, [])
    assert "jtsampai30" in sql and "jtlebih90" in sql
    assert params == [None]


def test_sql_stock_order_sisa():
    sql, _ = dm.sql_stock_menipis(dm.PROFIL_OTOBITZ, [], limit=10)
    assert "stockawal + masuk - keluar" in sql
    assert "LIMIT 10" in sql


def test_tanpa_interpolasi_input_user():
    """Nilai tanggal/cabang TIDAK BOLEH muncul di teks SQL (wajib via params).

    Ini pengganti gerbang verifier untuk SQL dashboard: SQL 100% dari kode.
    """
    aneh_tanggal = "2025-13-99'; DROP TABLE x; --"
    aneh_cabang = ["210'; DROP TABLE y; --"]
    builders = [
        dm.sql_spk_ringkasan, dm.sql_spk_bulanan, dm.sql_penjualan_ringkasan,
        dm.sql_penjualan_bulanan, dm.sql_unit_nilai, dm.sql_top_tipe,
        dm.sql_top_leasing, dm.sql_wo_ringkasan, dm.sql_wo_bulanan,
        dm.sql_wo_per_sa, dm.sql_faktur_ringkasan, dm.sql_faktur_bulanan,
    ]
    for b in builders:
        sql, params = b(dm.PROFIL_OTOBITZ, aneh_tanggal, aneh_tanggal,
                        aneh_cabang)
        assert "DROP" not in sql
        assert aneh_tanggal not in sql
        assert params[0] == aneh_tanggal and params[2] == aneh_cabang
    sql, params = dm.sql_ar_aging(dm.PROFIL_OTOBITZ, aneh_cabang)
    assert "DROP" not in sql and params == [aneh_cabang]
