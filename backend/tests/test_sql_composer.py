"""
Test sql_composer (F2.2) — rencana JSON -> SQL deterministik parameterized.

Pola: plain pytest TANPA DB (mengikuti tests/test_sql_guard.py), bukan asyncio.
Skema tenant dipakai dari fixture `schema_config_dealer` (tests/conftest.py) —
bentuk hasil introspeksi ASLI (columns = [{name, type}], foreign_keys =
[{column, references_table, references_column}]) — TIDAK membuat skema sendiri.

Setiap kasus POSITIF lewat compose_sql(), yang di dalamnya WAJIB lolos
verify_sql() (belt-and-suspenders) — lulus berarti struktur SQL terverifikasi
oleh verifier F2.3'. Asersi baku per positif (lihat _komposisi):
  1. placeholder $1..$n persis cocok jumlah params (gaya asyncpg);
  2. SQL bebas literal nilai (tanpa kutip-tunggal, tanpa angka selain LIMIT);
  3. SQL single-statement (tanpa ';').
"""
import re
from datetime import date, datetime

import pytest

from app.services.sql_composer import (
    compose_sql,
    ganti_placeholder_null,
    SqlComposerError,
    validate_plan,
)

# `now` tetap untuk seluruh kasus preset/custom — TZ keputusan pemanggil.
# 2026-03-15 = Minggu (basis perhitungan pekan ISO: Senin = 09 Mar).
NOW_TETAP = datetime(2026, 3, 15, 10, 30)


# ============================================================================
# Util asersi baku
# ============================================================================
def _rapikan_sql(sql: str) -> str:
    """Buang 'LIMIT <angka>' (satu-satunya literal angka yang sah) dan tanda
    placeholder $n — sisa SQL harus bebas digit dan kutip-tunggal."""
    tanpa_limit = re.sub(r"LIMIT \d+$", "", sql)
    return re.sub(r"\$\d+", "$", tanpa_limit)


def _komposisi(plan, schema_config, now=NOW_TETAP, jumlah_params=0):
    """compose_sql + asersi baku positif. verify_sql dijalankan internal
    compose_sql; bila ditolak composer sendiri yang raise."""
    hasil = compose_sql(plan, schema_config, now=now)
    sql = hasil["sql"]
    nomor = [int(m[1:]) for m in re.findall(r"\$\d+", sql)]
    assert nomor == list(range(1, jumlah_params + 1)), f"placeholder: {sql}"
    assert len(hasil["params"]) == jumlah_params, f"params: {sql}"
    inti = _rapikan_sql(sql)
    assert "'" not in inti, f"literal string bocor ke SQL: {sql}"
    assert not re.search(r"\d", inti), f"literal angka bocor ke SQL: {sql}"
    assert ";" not in sql, f"multi-statement: {sql}"
    return hasil


def _plan_dasar(**over):
    """Rencana valid minimal (tabel penjualan, kolom plain tanpa agregasi) —
    titik awal untuk kasus negatif agar hanya cacat yang disuntikkan muncul."""
    plan = {"tables": ["penjualan"], "columns": ["penjualan.nama_sales"]}
    plan.update(over)
    return plan


# ============================================================================
# POSITIF
# ============================================================================
class TestPositif:
    def test_kolom_polos_satu_tabel(self, schema_config_dealer):
        hasil = _komposisi(
            {"tables": ["penjualan"], "columns": ["penjualan.nama_sales"]},
            schema_config_dealer, jumlah_params=0)
        assert hasil["sql"] == (
            'SELECT "penjualan"."nama_sales" FROM "penjualan" LIMIT 200')
        assert hasil["used_tables"] == ["penjualan"]
        assert hasil["limit"] == 200

    def test_agregat_alias_join_group_order(self, schema_config_dealer):
        # Smoke plan yang dipakai repro bug _fk_join_chain: 2 tabel via FK,
        # kolom plain + agregat, preset, group, order by alias.
        plan = {
            "tables": ["penjualan", "kendaraan"],
            "columns": [
                "kendaraan.merek",
                {"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"},
            ],
            "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},
            "group_by": ["kendaraan.merek"],
            "order_by": [{"by": "omzet", "dir": "DESC"}],
            "limit": 50,
        }
        hasil = _komposisi(plan, schema_config_dealer, jumlah_params=2)
        assert hasil["sql"] == (
            'SELECT "kendaraan"."merek", SUM("penjualan"."harga_deal") AS "omzet" '
            'FROM "penjualan" JOIN "kendaraan" ON "kendaraan"."id" = '
            '"penjualan"."kendaraan_id" WHERE "penjualan"."tanggal" >= $1 AND '
            '"penjualan"."tanggal" < $2 GROUP BY "kendaraan"."merek" '
            'ORDER BY "omzet" DESC LIMIT 50')
        assert hasil["params"] == [date(2026, 3, 1), date(2026, 4, 1)]
        assert hasil["used_tables"] == ["kendaraan", "penjualan"]

    def test_count_star_alias_group_order(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": [{"agg": "COUNT", "column": "*", "alias": "jumlah"}],
            "group_by": ["penjualan.nama_sales"],
            "order_by": [{"by": "jumlah", "dir": "DESC"}],
        }, schema_config_dealer, jumlah_params=0)
        assert 'COUNT(*) AS "jumlah"' in hasil["sql"]
        assert 'GROUP BY "penjualan"."nama_sales"' in hasil["sql"]
        assert 'ORDER BY "jumlah" DESC' in hasil["sql"]

    def test_agregat_multi_tanpa_alias(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": [
                {"agg": "MIN", "column": "penjualan.harga_deal"},
                {"agg": "MAX", "column": "penjualan.harga_deal"},
            ],
        }, schema_config_dealer, jumlah_params=0)
        assert 'MIN("penjualan"."harga_deal"), MAX("penjualan"."harga_deal")' \
            in hasil["sql"]
        assert " AS " not in hasil["sql"]

    @pytest.mark.parametrize("op,simbol", [
        ("eq", "="), ("neq", "<>"), ("gt", ">"),
        ("gte", ">="), ("lt", "<"), ("lte", "<="),
    ])
    def test_filter_skalar(self, schema_config_dealer, op, simbol):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.id"],
            "filters": [{"column": "penjualan.harga_deal", "op": op,
                         "value": 123456789}],
        }, schema_config_dealer, jumlah_params=1)
        assert (f'"penjualan"."harga_deal" {simbol} $1' in hasil["sql"])
        assert hasil["params"] == [123456789]

    def test_filter_like(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["kendaraan"],
            "columns": ["kendaraan.nomor_rangka"],
            "filters": [{"column": "kendaraan.merek", "op": "like",
                         "value": "%Toyota%"}],
        }, schema_config_dealer, jumlah_params=1)
        assert '"kendaraan"."merek" LIKE $1' in hasil["sql"]
        assert hasil["params"] == ["%Toyota%"]

    def test_filter_in(self, schema_config_dealer):
        nilai = ["cash", "credit", "tempo"]
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.id"],
            "filters": [{"column": "penjualan.metode_pembayaran", "op": "in",
                         "value": nilai}],
        }, schema_config_dealer, jumlah_params=3)
        assert '"penjualan"."metode_pembayaran" IN ($1, $2, $3)' in hasil["sql"]
        assert hasil["params"] == nilai

    def test_filter_between(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.id"],
            "filters": [{"column": "penjualan.harga_deal", "op": "between",
                         "value": [10000000, 50000000]}],
        }, schema_config_dealer, jumlah_params=2)
        assert '"penjualan"."harga_deal" BETWEEN $1 AND $2' in hasil["sql"]
        assert hasil["params"] == [10000000, 50000000]

    def test_filter_is_null(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["kendaraan"],
            "columns": ["kendaraan.merek"],
            "filters": [{"column": "kendaraan.warna", "op": "is_null"}],
        }, schema_config_dealer, jumlah_params=0)
        assert '"kendaraan"."warna" IS NULL' in hasil["sql"]

    def test_filter_is_not_null(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.nama_sales"],
            "filters": [{"column": "penjualan.catatan", "op": "is_not_null"}],
        }, schema_config_dealer, jumlah_params=0)
        assert '"penjualan"."catatan" IS NOT NULL' in hasil["sql"]

    # --- preset waktu: semua preset dengan `now` tetap -----------------------
    @pytest.mark.parametrize("preset,dua_batas", [
        ("this_month", (date(2026, 3, 1), date(2026, 4, 1))),
        ("last_month", (date(2026, 2, 1), date(2026, 3, 1))),
        ("this_week", (date(2026, 3, 9), date(2026, 3, 16))),
        ("last_week", (date(2026, 3, 2), date(2026, 3, 9))),
        ("last_7_days", (date(2026, 3, 9), date(2026, 3, 16))),
        ("last_30_days", (date(2026, 2, 14), date(2026, 3, 16))),
        ("this_year", (date(2026, 1, 1), date(2027, 1, 1))),
    ])
    def test_preset_waktu(self, schema_config_dealer, preset, dua_batas):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.nama_sales"],
            "time_range": {"field": "penjualan.tanggal", "preset": preset},
        }, schema_config_dealer, jumlah_params=2)
        assert hasil["params"] == list(dua_batas)
        assert '"penjualan"."tanggal" >= $1' in hasil["sql"]
        assert '"penjualan"."tanggal" < $2' in hasil["sql"]

    def test_custom_range_date(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.nama_sales"],
            "time_range": {"field": "penjualan.tanggal", "from": "2026-01-01",
                           "to": "2026-01-31"},
        }, schema_config_dealer, jumlah_params=2)
        assert hasil["params"] == [date(2026, 1, 1), date(2026, 1, 31)]
        assert '"penjualan"."tanggal" <= $2' in hasil["sql"]

    def test_custom_range_datetime(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.nama_sales"],
            "time_range": {"field": "penjualan.tanggal",
                           "from": "2026-01-01T00:00:00",
                           "to": "2026-01-31T23:59:59"},
        }, schema_config_dealer, jumlah_params=2)
        assert hasil["params"] == [datetime(2026, 1, 1, 0, 0, 0),
                                   datetime(2026, 1, 31, 23, 59, 59)]

    @pytest.mark.parametrize("minta,akhir", [
        (501, 500), (99999, 500), (0, 1), (-5, 1), (1, 1), (75, 75),
    ])
    def test_limit_clamp(self, schema_config_dealer, minta, akhir):
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.id"],
            "limit": minta,
        }, schema_config_dealer, jumlah_params=0)
        assert hasil["limit"] == akhir
        assert hasil["sql"].endswith(f"LIMIT {akhir}")

    def test_limit_default_200(self, schema_config_dealer):
        hasil = _komposisi(
            {"tables": ["penjualan"], "columns": ["penjualan.id"]},
            schema_config_dealer, jumlah_params=0)
        assert hasil["limit"] == 200
        assert hasil["sql"].endswith("LIMIT 200")

    def test_distinct(self, schema_config_dealer):
        hasil = _komposisi({
            "tables": ["pelanggan"],
            "columns": ["pelanggan.kota"],
            "distinct": True,
            "order_by": [{"by": "pelanggan.kota", "dir": "ASC"}],
        }, schema_config_dealer, jumlah_params=0)
        assert hasil["sql"].startswith('SELECT DISTINCT "pelanggan"."kota"')
        assert 'ORDER BY "pelanggan"."kota" ASC' in hasil["sql"]

    def test_gabungan_lengkap(self, schema_config_dealer):
        # kolom plain + agregat, 2 filter, time_range preset, group, 2 order_by,
        # limit, field presentasional — semuanya sekaligus.
        plan = {
            "tables": ["penjualan", "kendaraan"],
            "columns": [
                "kendaraan.merek",
                {"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"},
            ],
            "filters": [
                {"column": "penjualan.metode_pembayaran", "op": "eq",
                 "value": "cash"},
                {"column": "penjualan.harga_deal", "op": "gt", "value": 5000000},
            ],
            "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},
            "group_by": ["kendaraan.merek"],
            "order_by": [
                {"by": "omzet", "dir": "DESC"},
                {"by": "kendaraan.merek", "dir": "ASC"},
            ],
            "limit": 100,
            "intent": "bar chart",
            "chart_hint": "bar",
            "answer_style": "ringkas",
        }
        hasil = _komposisi(plan, schema_config_dealer, jumlah_params=4)
        assert hasil["sql"] == (
            'SELECT "kendaraan"."merek", SUM("penjualan"."harga_deal") AS "omzet" '
            'FROM "penjualan" JOIN "kendaraan" ON "kendaraan"."id" = '
            '"penjualan"."kendaraan_id" WHERE "penjualan"."metode_pembayaran" = $1 '
            'AND "penjualan"."harga_deal" > $2 AND "penjualan"."tanggal" >= $3 '
            'AND "penjualan"."tanggal" < $4 GROUP BY "kendaraan"."merek" '
            'ORDER BY "omzet" DESC, "kendaraan"."merek" ASC LIMIT 100')
        assert hasil["params"] == ["cash", 5000000,
                                   date(2026, 3, 1), date(2026, 4, 1)]

    def test_fk_chain_tiga_tabel(self, schema_config_dealer):
        # detail_penjualan -> penjualan -> kendaraan: dua JOIN berantai.
        hasil = _komposisi({
            "tables": ["detail_penjualan", "penjualan", "kendaraan"],
            "columns": ["detail_penjualan.komponen", "kendaraan.merek"],
            "group_by": ["detail_penjualan.komponen", "kendaraan.merek"],
            "order_by": [{"by": "detail_penjualan.komponen"}],
        }, schema_config_dealer, jumlah_params=0)
        assert ('JOIN "penjualan" ON "penjualan"."id" = '
                '"detail_penjualan"."penjualan_id"' in hasil["sql"])
        assert ('JOIN "kendaraan" ON "kendaraan"."id" = '
                '"penjualan"."kendaraan_id"' in hasil["sql"])
        assert hasil["used_tables"] == ["detail_penjualan", "kendaraan",
                                        "penjualan"]

    def test_tabel_perantara_otomatis_di_join(self, schema_config_dealer):
        # penjualan TIDAK dicantumkan di plan.tables, tapi wajib di-join
        # sebagai perantara path detail_penjualan -> kendaraan.
        hasil = _komposisi({
            "tables": ["detail_penjualan", "kendaraan"],
            "columns": ["detail_penjualan.komponen", "kendaraan.merek"],
            "group_by": ["detail_penjualan.komponen", "kendaraan.merek"],
        }, schema_config_dealer, jumlah_params=0)
        assert hasil["used_tables"] == ["detail_penjualan", "kendaraan",
                                        "penjualan"]
        assert '"penjualan"' in hasil["sql"]

    def test_field_presentasional_tidak_memengaruhi_sql(self, schema_config_dealer):
        dasar = {
            "tables": ["penjualan"],
            "columns": ["penjualan.nama_sales"],
            "time_range": {"field": "penjualan.tanggal", "preset": "this_week"},
        }
        a = _komposisi(dasar, schema_config_dealer, jumlah_params=2)
        b = _komposisi({**dasar,
                        "intent": "tren mingguan",
                        "chart_hint": "line",
                        "answer_style": "paragraf"},
                       schema_config_dealer, jumlah_params=2)
        assert a["sql"] == b["sql"]
        assert a["params"] == b["params"]

    def test_urutan_params_filter_lalu_time_range(self, schema_config_dealer):
        # Nilai muncul sesuai urutan di SQL: filter (urut rencana) dulu,
        # lalu batas time_range.
        hasil = _komposisi({
            "tables": ["penjualan"],
            "columns": ["penjualan.nama_sales"],
            "filters": [
                {"column": "penjualan.metode_pembayaran", "op": "eq",
                 "value": "cash"},
                {"column": "penjualan.harga_deal", "op": "gt", "value": 1000000},
            ],
            "time_range": {"field": "penjualan.tanggal",
                           "preset": "last_7_days"},
        }, schema_config_dealer, jumlah_params=4)
        assert hasil["params"] == ["cash", 1000000,
                                   date(2026, 3, 9), date(2026, 3, 16)]
        assert hasil["sql"].count("$1") == 1 and "$4" in hasil["sql"]

    def test_kontrak_clean_plan_validate(self, schema_config_dealer):
        # validate_plan: agg/dir dinormalkan huruf besar, nilai filter
        # dipertahankan, is_null tanpa "value", presentasional diteruskan.
        plan = {
            "tables": ["penjualan"],
            "columns": [{"agg": "sum", "column": "penjualan.harga_deal",
                         "alias": "omzet"}],
            "filters": [
                {"column": "penjualan.metode_pembayaran", "op": "eq",
                 "value": "cash"},
                {"column": "penjualan.catatan", "op": "is_null"},
            ],
            "order_by": [{"by": "omzet", "dir": "desc"}],
            "intent": "uji",
        }
        clean, errs = validate_plan(plan, schema_config_dealer)
        assert errs == []
        assert clean["columns"] == [{"agg": "SUM", "column": "penjualan.harga_deal",
                                     "alias": "omzet"}]
        assert clean["filters"] == [
            {"column": "penjualan.metode_pembayaran", "op": "eq", "value": "cash"},
            {"column": "penjualan.catatan", "op": "is_null"},
        ]
        assert clean["order_by"] == [{"by": "omzet", "dir": "DESC"}]
        assert clean["intent"] == "uji"
        # clean_plan harus langsung bisa di-compose (round-trip).
        _komposisi(clean, schema_config_dealer, jumlah_params=1)

    def test_ganti_placeholder_null(self):
        sql = 'SELECT "a" FROM "t" WHERE "x" >= $1 AND "y" < $2 LIMIT 10'
        assert ganti_placeholder_null(sql) == (
            'SELECT "a" FROM "t" WHERE "x" >= NULL AND "y" < NULL LIMIT 10')


# ============================================================================
# NEGATIF — rencana tidak valid (ditolak di validate_plan)
# ============================================================================
NEGATIF_VALIDATE = [
    # (id, plan, potongan_pesan)
    ("tabel-asing", {"tables": ["stok_gudang"], "columns": ["stok_gudang.id"]},
     "tabel 'stok_gudang' tidak ada di skema"),
    ("kolom-asing", _plan_dasar(columns=["penjualan.harga_otr"]),
     "kolom 'harga_otr' tidak ada di tabel 'penjualan'"),
    ("agg-asing-string_agg", _plan_dasar(columns=[
        {"agg": "STRING_AGG", "column": "penjualan.nama_sales"}]),
     "agg hanya"),
    ("agg-asing-pg_sleep", _plan_dasar(columns=[
        {"agg": "PG_SLEEP", "column": "penjualan.id"}]),
     "agg hanya"),
    ("op-asing", _plan_dasar(filters=[
        {"column": "penjualan.id", "op": "ilike", "value": "%x%"}]),
     "op tidak dikenal"),
    ("in-bukan-list", _plan_dasar(filters=[
        {"column": "penjualan.metode_pembayaran", "op": "in", "value": "cash"}]),
     "wajib list value tidak kosong"),
    ("in-list-kosong", _plan_dasar(filters=[
        {"column": "penjualan.metode_pembayaran", "op": "in", "value": []}]),
     "wajib list value tidak kosong"),
    ("between-1-item", _plan_dasar(filters=[
        {"column": "penjualan.harga_deal", "op": "between", "value": [1000]}]),
     "wajib list tepat 2 nilai"),
    ("between-terbalik", _plan_dasar(filters=[
        {"column": "penjualan.harga_deal", "op": "between",
         "value": [50000000, 10000000]}]),
     "batas terbalik"),
    ("like-bukan-string", _plan_dasar(filters=[
        {"column": "penjualan.nama_sales", "op": "like", "value": 123}]),
     "wajib value string pola"),
    ("alias-jahat", _plan_dasar(columns=[
        {"agg": "SUM", "column": "penjualan.harga_deal",
         "alias": "omzet; DROP TABLE x"}]),
     "tidak cocok pola"),
    ("alias-duplikat", _plan_dasar(columns=[
        {"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"},
        {"agg": "COUNT", "column": "*", "alias": "omzet"}]),
     "alias duplikat"),
    ("tables-kosong", _plan_dasar(tables=[]),
     "tables wajib list berisi minimal satu nama tabel"),
    ("tables-bukan-list", _plan_dasar(tables="penjualan"),
     "tables wajib list berisi minimal satu nama tabel"),
    ("tabel-duplikat", _plan_dasar(tables=["penjualan", "penjualan"]),
     "tabel duplikat dalam rencana"),
    ("field-top-level-asing", _plan_dasar(**{"hallucination": "x"}),
     "field tak dikenal: 'hallucination'"),
    ("group-by-invalid", _plan_dasar(group_by=["penjualan.harga_otr"]),
     "kolom 'harga_otr' tidak ada di tabel 'penjualan'"),
    ("group-by-bukan-list", _plan_dasar(group_by="penjualan.nama_sales"),
     "group_by wajib list 'tabel.kolom' tidak kosong"),
    ("order-by-alias-tak-dikenal", _plan_dasar(
        columns=[{"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"}],
        order_by=[{"by": "omzet_palsu"}]),
     "bukan alias SELECT dan bukan kolom sah"),
    ("order-by-kolom-tanpa-group-agg", _plan_dasar(
        columns=[{"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"}],
        order_by=[{"by": "penjualan.nama_sales"}]),
     "wajib merujuk alias SELECT"),
    ("order-by-kolom-di-luar-group-by", _plan_dasar(
        columns=[{"agg": "COUNT", "column": "*", "alias": "jumlah"}],
        group_by=["penjualan.nama_sales"],
        order_by=[{"by": "penjualan.id"}]),
     "wajib masuk group_by"),
    ("dir-asing", _plan_dasar(order_by=[
        {"by": "penjualan.nama_sales", "dir": "DROP"}]),
     "dir hanya ASC/DESC"),
    ("order-by-bukan-objek", _plan_dasar(order_by=[42]),
     "objek hanya boleh {by, dir?}"),
    ("time-range-field-bukan-tanggal", _plan_dasar(time_range={
        "field": "penjualan.nama_sales", "preset": "this_month"}),
     "wajib bertipe tanggal/timestamp"),
    ("time-range-preset-tak-dikenal", _plan_dasar(time_range={
        "field": "penjualan.tanggal", "preset": "besok"}),
     "preset tidak dikenal"),
    ("time-range-preset-dan-range", _plan_dasar(time_range={
        "field": "penjualan.tanggal", "preset": "this_month",
        "from": "2026-01-01", "to": "2026-01-31"}),
     "pilih preset ATAU from/to"),
    ("time-range-from-tanpa-to", _plan_dasar(time_range={
        "field": "penjualan.tanggal", "from": "2026-01-01"}),
     "from dan to wajib bersamaan"),
    ("time-range-from-di-atas-to", _plan_dasar(time_range={
        "field": "penjualan.tanggal", "from": "2026-02-01", "to": "2026-01-01"}),
     "from harus <= to"),
    ("time-range-bukan-iso", _plan_dasar(time_range={
        "field": "penjualan.tanggal", "from": "kemarin", "to": "lusa"}),
     "bukan ISO date/datetime yang sah"),
    ("time-range-bukan-objek", _plan_dasar(time_range="this_month"),
     "time_range wajib objek"),
    ("filter-eq-tanpa-value", _plan_dasar(filters=[
        {"column": "penjualan.id", "op": "eq"}]),
     "wajib value scalar"),
    ("filter-eq-value-null", _plan_dasar(filters=[
        {"column": "penjualan.id", "op": "eq", "value": None}]),
     "wajib value scalar"),
    ("filter-is-null-dengan-value", _plan_dasar(filters=[
        {"column": "penjualan.catatan", "op": "is_null", "value": "x"}]),
     "tidak memakai value"),
    ("filter-bukan-objek", _plan_dasar(filters=[42]),
     "wajib objek {column, op, value?}"),
    ("filter-kunci-asing", _plan_dasar(filters=[
        {"column": "penjualan.id", "op": "eq", "value": 1, "hack": 1}]),
     "kunci tak dikenal"),
    ("columns-bukan-list", _plan_dasar(columns="penjualan.id"),
     "columns wajib list berisi minimal satu kolom"),
    ("columns-entri-asing", _plan_dasar(columns=[42]),
     "entri harus string 'tabel.kolom' atau objek"),
    ("kolom-tabel-di-luar-rencana", _plan_dasar(
        tables=["penjualan", "kendaraan"],
        columns=["detail_penjualan.komponen"]),
     "merujuk tabel di luar rencana"),
    ("campur-agregat-plain-tanpa-group", _plan_dasar(columns=[
        "penjualan.nama_sales",
        {"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"}]),
     "mencampur agregat dan kolom plain tanpa group_by"),
    ("kolom-plain-wajib-group-by", _plan_dasar(
        columns=["penjualan.nama_sales", "penjualan.catatan"],
        group_by=["penjualan.nama_sales"]),
     "wajib masuk group_by"),
    ("limit-bukan-integer", _plan_dasar(limit="banyak"),
     "limit wajib integer"),
    ("distinct-bukan-boolean", _plan_dasar(distinct="ya"),
     "distinct wajib boolean"),
    ("kolom-bukan-ref", _plan_dasar(columns=["harga_deal"]),
     "referensi kolom harus 'tabel.kolom'"),
]


class TestNegatif:
    @pytest.mark.parametrize("plan,potongan",
                             [p[1:] for p in NEGATIF_VALIDATE],
                             ids=[p[0] for p in NEGATIF_VALIDATE])
    def test_rencana_ditolak_validate(self, schema_config_dealer, plan, potongan):
        # compose_sql memanggil validate_plan di dalamnya — kegagalan selalu
        # jadi SqlComposerError (HTTP 400), bukan crash TypeError/KeyError.
        with pytest.raises(SqlComposerError) as exc:
            compose_sql(plan, schema_config_dealer)
        assert potongan in str(exc.value)

    def test_fk_path_tak_terhubung_ditolak(self, schema_config_dealer):
        # Salinan fixture dilucuti seluruh FK-nya — pasangan tabel mana pun
        # kini tak terhubung (fixture memang deepcopy "bebas dimodifikasi").
        import copy
        skema_tanpa_fk = copy.deepcopy(schema_config_dealer)
        for info in skema_tanpa_fk["tables"].values():
            info["foreign_keys"] = []
        plan = {
            "tables": ["kendaraan", "pelanggan"],
            "columns": ["kendaraan.merek", "pelanggan.nama"],
            "group_by": ["kendaraan.merek", "pelanggan.nama"],
        }
        with pytest.raises(SqlComposerError) as exc:
            compose_sql(plan, skema_tanpa_fk)
        assert "tidak ada FK path dari 'kendaraan' ke: pelanggan" \
            in str(exc.value)

    def test_fk_path_tak_berarah_via_perantara(self, schema_config_dealer):
        # kendaraan + pelanggan tak ber-FK langsung, tapi graph FK dibaca
        # tak berarah: kendaraan <- penjualan -> pelanggan (2 auto-join).
        hasil = _komposisi({
            "tables": ["kendaraan", "pelanggan"],
            "columns": ["kendaraan.merek", "pelanggan.nama"],
            "group_by": ["kendaraan.merek", "pelanggan.nama"],
        }, schema_config_dealer, jumlah_params=0)
        assert ('JOIN "penjualan" ON "penjualan"."kendaraan_id" = '
                '"kendaraan"."id"' in hasil["sql"])
        assert ('JOIN "pelanggan" ON "pelanggan"."id" = '
                '"penjualan"."pelanggan_id"' in hasil["sql"])
        assert hasil["used_tables"] == ["kendaraan", "pelanggan", "penjualan"]

    @pytest.mark.parametrize("now_buruk", [None, date(2026, 3, 15)])
    def test_preset_tanpa_now_ditolak(self, schema_config_dealer, now_buruk):
        # `now` wajib datetime (bukan date, bukan None) bila pakai preset.
        plan = _plan_dasar(time_range={
            "field": "penjualan.tanggal", "preset": "this_month"})
        with pytest.raises(SqlComposerError) as exc:
            compose_sql(plan, schema_config_dealer, now=now_buruk)
        assert "preset time_range wajib `now` bertipe datetime" in str(exc.value)

    # --- injeksi via nilai: TIDAK boleh masuk SQL, harus jadi param ---------
    def test_injeksi_value_eq_masuk_params(self, schema_config_dealer):
        jahat = "'; DROP TABLE penjualan; --"
        plan = _plan_dasar(filters=[
            {"column": "penjualan.metode_pembayaran", "op": "eq", "value": jahat}])
        hasil = _komposisi(plan, schema_config_dealer, jumlah_params=1)
        assert hasil["params"] == [jahat]
        assert "DROP TABLE" not in hasil["sql"].upper()
        assert "'" not in hasil["sql"]

    def test_injeksi_value_di_list_in_masuk_params(self, schema_config_dealer):
        jahat = "x') UNION SELECT pg_sleep(10); --"
        plan = _plan_dasar(filters=[
            {"column": "penjualan.metode_pembayaran", "op": "in",
             "value": ["cash", jahat]}])
        hasil = _komposisi(plan, schema_config_dealer, jumlah_params=2)
        assert hasil["params"][1] == jahat
        assert "pg_sleep" not in hasil["sql"].lower()
        assert "UNION" not in hasil["sql"].upper()


# ============================================================================
# DETERMINISME
# ============================================================================
class TestDeterminisme:
    _PLAN = {
        "tables": ["penjualan", "kendaraan"],
        "columns": [
            "kendaraan.merek",
            {"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"},
        ],
        "filters": [{"column": "penjualan.metode_pembayaran", "op": "eq",
                     "value": "cash"}],
        "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},
        "group_by": ["kendaraan.merek"],
        "order_by": [{"by": "omzet", "dir": "DESC"}],
        "limit": 50,
    }

    def test_compose_dua_kali_identik_byte_per_byte(self, schema_config_dealer):
        a = compose_sql(self._PLAN, schema_config_dealer, now=NOW_TETAP)
        b = compose_sql(self._PLAN, schema_config_dealer, now=NOW_TETAP)
        assert a["sql"] == b["sql"]  # byte-per-byte
        assert a["params"] == b["params"]
        assert a["used_tables"] == b["used_tables"]
        assert a["limit"] == b["limit"]

    def test_now_beda_bulan_mengubah_batas_benar(self, schema_config_dealer):
        # Parameterisasi penuh: teks SQL identik (nilai selalu di params),
        # tetapi batas efektif berubah benar mengikuti bulan `now`.
        feb = compose_sql(self._PLAN, schema_config_dealer,
                          now=datetime(2026, 2, 15, 9, 0))
        mar = compose_sql(self._PLAN, schema_config_dealer,
                          now=datetime(2026, 3, 15, 9, 0))
        assert feb["sql"] == mar["sql"]
        assert feb["params"] == ["cash", date(2026, 2, 1), date(2026, 3, 1)]
        assert mar["params"] == ["cash", date(2026, 3, 1), date(2026, 4, 1)]
        assert feb["params"] != mar["params"]

    def test_preset_bergeser_merentang_bulan(self, schema_config_dealer):
        # last_month dari now di pertengahan Maret = Februari; dari now di
        # pertengahan Februari = Januari — batas ikut bergeser benar.
        plan = {"tables": ["penjualan"], "columns": ["penjualan.nama_sales"],
                "time_range": {"field": "penjualan.tanggal",
                               "preset": "last_month"}}
        maret = compose_sql(plan, schema_config_dealer,
                            now=datetime(2026, 3, 15, 9, 0))
        februari = compose_sql(plan, schema_config_dealer,
                               now=datetime(2026, 2, 15, 9, 0))
        assert maret["params"] == [date(2026, 2, 1), date(2026, 3, 1)]
        assert februari["params"] == [date(2026, 1, 1), date(2026, 2, 1)]
