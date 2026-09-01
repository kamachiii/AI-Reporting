"""
Test knowledge_base service (F2.0) — validasi ketat & load default.

Tidak butuh database: load_kb diuji dengan pool stub (fetchrow async
sederhana). pytest-asyncio tidak tersedia, jadi skenario async dibungkus
asyncio.run di dalam test sinkron.
"""
import asyncio

from app.services.knowledge_base import (
    EMPTY_KB,
    load_kb,
    parse_stored_kb,
    validate_kb,
)


class _StubPool:
    """Pool asyncpg mini: fetchrow mengembalikan apa yang di-set test."""

    def __init__(self, row):
        self.row = row
        self.captured_args = None

    async def fetchrow(self, sql, *args):
        # Query di service wajib parameterized ($1) — tangkap buktinya.
        self.captured_args = (sql, args)
        return self.row


class _StubRow(dict):
    """Record asyncpg mini: akses per kolom via ['nama_kolom']."""

    def __getitem__(self, key):
        return dict.__getitem__(self, key)


# Contoh KB penuh — disalin dari docs/PERANCANGAN-PIPELINE-AI.md §3.
# `tabel_diizinkan` ditambahkan di fase skema efektif (allowlist per tenant);
# `kolom_dikecualikan` menyusul untuk hemat token prompt planner.
KB_PENUH = {
    "glossary": [
        {"istilah": "omzet", "arti": "SUM(penjualan.harga_deal)"},
        {"istilah": "unit laku", "arti": "COUNT(*) dari penjualan"},
        {"istilah": "prospek", "arti": "pelanggan belum beli (tanpa penjualan)"},
    ],
    "catatan_kolom": {
        "penjualan.harga_deal": "Harga final setelah negosiasi",
        "penjualan.uang_muka": "0 artinya tunai",
    },
    "nilai_map": {
        "penjualan.metode_pembayaran": {"cash": "tunai", "credit": "kredit"},
    },
    "contoh_tanya": [
        {"tanya": "omzet bulan ini", "tabel": ["penjualan"],
         "agg": "sum(harga_deal)", "time_range": "this_month"},
    ],
    "tabel_dilarang": ["log_audit_internal"],
    "tabel_diizinkan": ["penjualan", "kendaraan"],
    "kolom_dikecualikan": ["penjualan.api_key", "users.token_hash"],
}


class TestValidateKb:
    def test_valid_minimal_dict_kosong(self):
        # {} = valid minimal: semua bagian opsional, dinormalisasi jadi struktur kosong
        clean, errors = validate_kb({})
        assert errors == []
        assert clean == EMPTY_KB

    def test_valid_penuh(self):
        clean, errors = validate_kb(KB_PENUH)
        assert errors == []
        assert clean == KB_PENUH

    def test_field_tak_dikenal_error(self):
        clean, errors = validate_kb({"glossary": [], "rag_embedding": True})
        assert any("rag_embedding" in e and "tidak dikenal" in e for e in errors)
        # clean tetap bentuk normal (5 field), tapi TIDAK layak simpan (errors non-kosong)
        assert set(clean.keys()) == set(EMPTY_KB.keys())
        assert errors

    def test_glossary_entry_kosong_error(self):
        _, errors = validate_kb({"glossary": [{"istilah": "", "arti": "SUM(x)"}]})
        assert any("glossary[0]" in e and "istilah" in e for e in errors)

        _, errors = validate_kb({"glossary": [{"istilah": "omzet"}]})
        assert any("glossary[0]" in e and "arti" in e for e in errors)

        _, errors = validate_kb({"glossary": [{"istilah": " ", "arti": None}]})
        assert errors

    def test_glossary_field_asing_error(self):
        _, errors = validate_kb(
            {"glossary": [{"istilah": "omzet", "arti": "SUM(x)", "embedding": [1]}]})
        assert any("embedding" in e and "tidak dikenal" in e for e in errors)

    def test_nilai_map_salah_tipe_error(self):
        # value bukan dict
        _, errors = validate_kb(
            {"nilai_map": {"penjualan.metode_pembayaran": "tunai"}})
        assert any("nilai_map" in e for e in errors)
        # inner value bukan string
        _, errors = validate_kb(
            {"nilai_map": {"penjualan.metode_pembayaran": {"cash": 1}}})
        assert any("nilai_map" in e for e in errors)

    def test_tabel_dilarang_salah_tipe_error(self):
        # string, bukan array
        _, errors = validate_kb({"tabel_dilarang": "log_audit_internal"})
        assert any("tabel_dilarang" in e for e in errors)
        # array berisi non-string
        _, errors = validate_kb({"tabel_dilarang": [1, 2]})
        assert any("tabel_dilarang" in e for e in errors)
        # array berisi string kosong
        _, errors = validate_kb({"tabel_dilarang": ["  "]})
        assert any("tabel_dilarang" in e for e in errors)

    def test_tabel_diizinkan_valid(self):
        clean, errors = validate_kb(
            {"tabel_diizinkan": ["penjualan", "kendaraan"]})
        assert errors == []
        assert clean["tabel_diizinkan"] == ["penjualan", "kendaraan"]
        # di-strip; sisanya tetap bentuk normal (6 field)
        clean, errors = validate_kb({"tabel_diizinkan": [" penjualan "]})
        assert errors == []
        assert clean["tabel_diizinkan"] == ["penjualan"]
        assert set(clean.keys()) == set(EMPTY_KB.keys())

    def test_tabel_diizinkan_salah_tipe_error(self):
        # string, bukan array
        _, errors = validate_kb({"tabel_diizinkan": "penjualan"})
        assert any("tabel_diizinkan" in e for e in errors)
        # array berisi non-string
        _, errors = validate_kb({"tabel_diizinkan": ["penjualan", 7]})
        assert any("tabel_diizinkan" in e for e in errors)

    def test_tabel_diizinkan_entri_kosong_dan_pola_jahat_error(self):
        # entri kosong -> error per indeks
        _, errors = validate_kb({"tabel_diizinkan": ["  "]})
        assert any("tabel_diizinkan[0]" in e for e in errors)
        # pola jahat (spasi/SQL) -> error
        _, errors = validate_kb(
            {"tabel_diizinkan": ["penjualan; DROP TABLE users"]})
        assert any("tabel_diizinkan[0]" in e for e in errors)
        # diawali angka / mengandung tanda hubung -> error
        _, errors = validate_kb({"tabel_diizinkan": ["123tabel"]})
        assert any("tabel_diizinkan[0]" in e for e in errors)
        _, errors = validate_kb({"tabel_diizinkan": ["tabel-x"]})
        assert any("tabel_diizinkan[0]" in e for e in errors)
        # entri lain yang valid tidak ikut dilaporkan (error per indeks)
        _, errors = validate_kb({"tabel_diizinkan": ["123tabel", "penjualan"]})
        assert any("tabel_diizinkan[0]" in e for e in errors)
        assert not any("tabel_diizinkan[1]" in e for e in errors)

    def test_kolom_dikecualikan_valid(self):
        clean, errors = validate_kb(
            {"kolom_dikecualikan": ["penjualan.api_key", "users.token_hash"]})
        assert errors == []
        assert clean["kolom_dikecualikan"] == [
            "penjualan.api_key", "users.token_hash"]
        # di-strip; sisanya tetap bentuk normal (7 field)
        clean, errors = validate_kb(
            {"kolom_dikecualikan": [" penjualan.api_key "]})
        assert errors == []
        assert clean["kolom_dikecualikan"] == ["penjualan.api_key"]
        assert set(clean.keys()) == set(EMPTY_KB.keys())

    def test_kolom_dikecualikan_salah_tipe_error(self):
        # string, bukan array
        _, errors = validate_kb({"kolom_dikecualikan": "penjualan.api_key"})
        assert any("kolom_dikecualikan" in e for e in errors)
        # array berisi non-string
        _, errors = validate_kb({"kolom_dikecualikan": ["penjualan.api_key", 7]})
        assert any("kolom_dikecualikan" in e for e in errors)

    def test_kolom_dikecualikan_format_salah_error_per_indeks(self):
        # tanpa titik -> error
        _, errors = validate_kb({"kolom_dikecualikan": ["api_key"]})
        assert any("kolom_dikecualikan[0]" in e for e in errors)
        # lebih dari satu titik -> error
        _, errors = validate_kb({"kolom_dikecualikan": ["a.b.c"]})
        assert any("kolom_dikecualikan[0]" in e for e in errors)
        # diawali angka -> error
        _, errors = validate_kb({"kolom_dikecualikan": ["1tabel.kolom"]})
        assert any("kolom_dikecualikan[0]" in e for e in errors)
        # entri kosong -> error
        _, errors = validate_kb({"kolom_dikecualikan": ["  "]})
        assert any("kolom_dikecualikan[0]" in e for e in errors)
        # entri lain yang valid tidak ikut dilaporkan (error per indeks)
        _, errors = validate_kb(
            {"kolom_dikecualikan": ["1tabel.kolom", "penjualan.api_key"]})
        assert any("kolom_dikecualikan[0]" in e for e in errors)
        assert not any("kolom_dikecualikan[1]" in e for e in errors)

    def test_catatan_kolom_salah_tipe_error(self):
        _, errors = validate_kb({"catatan_kolom": ["penjualan.harga_deal"]})
        assert any("catatan_kolom" in e for e in errors)
        _, errors = validate_kb({"catatan_kolom": {"penjualan.harga_deal": 123}})
        assert any("catatan_kolom" in e for e in errors)

    def test_contoh_tanya_tanpa_tanya_error(self):
        _, errors = validate_kb({"contoh_tanya": [{"agg": "sum(x)"}]})
        assert any("contoh_tanya[0]" in e and "tanya" in e for e in errors)
        _, errors = validate_kb({"contoh_tanya": ["omzet bulan ini"]})
        assert any("contoh_tanya[0]" in e for e in errors)

    def test_payload_bukan_dict_error(self):
        for payload in ([], "kb", 7, None):
            clean, errors = validate_kb(payload)
            assert len(errors) == 1, payload
            assert "objek JSON" in errors[0]

    def test_error_dilaporkan_per_indeks(self):
        _, errors = validate_kb({
            "glossary": [
                {"istilah": "omzet", "arti": "SUM(x)"},   # entri 0 valid
                {"istilah": "", "arti": ""},              # entri 1 rusak
            ],
        })
        assert not any("glossary[0]" in e for e in errors)
        assert any("glossary[1]" in e for e in errors)


class TestParseStoredKb:
    def test_none_jadi_struktur_kosong(self):
        assert parse_stored_kb(None) == EMPTY_KB

    def test_string_json_diparse(self):
        import json
        kb = parse_stored_kb(json.dumps(KB_PENUH))
        assert kb == KB_PENUH

    def test_string_rusak_jadi_default(self):
        assert parse_stored_kb("{bukan json") == EMPTY_KB

    def test_dict_diterima_langsung(self):
        assert parse_stored_kb(KB_PENUH) == KB_PENUH

    def test_field_hilang_dinormalisasi(self):
        kb = parse_stored_kb({"glossary": [{"istilah": "omzet", "arti": "SUM(x)"}]})
        assert kb["glossary"] == [{"istilah": "omzet", "arti": "SUM(x)"}]
        assert kb["catatan_kolom"] == {}
        assert kb["tabel_dilarang"] == []
        assert kb["tabel_diizinkan"] == []  # default: tidak diset (skema penuh)
        assert kb["kolom_dikecualikan"] == []  # default: tidak ada yang dibuang


class TestLoadKb:
    def _jalankan(self, row):
        return asyncio.run(load_kb(_StubPool(row), "JKT_01"))

    def test_load_tenant_tak_ada_jadi_struktur_kosong(self):
        assert self._jalankan(None) == EMPTY_KB

    def test_load_null_jadi_struktur_kosong(self):
        assert self._jalankan(_StubRow({"knowledge_base": None})) == EMPTY_KB

    def test_load_isi_tersimpan(self):
        import json
        kb = self._jalankan(_StubRow({"knowledge_base": json.dumps(KB_PENUH)}))
        assert kb == KB_PENUH

    def test_load_query_parameterized(self):
        # Bukti tidak ada SQL dinamis: branch_code lewat parameter $1.
        pool = _StubPool(_StubRow({"knowledge_base": None}))
        asyncio.run(load_kb(pool, "JKT_01"))
        sql, args = pool.captured_args
        assert "$1" in sql and args == ("JKT_01",)
