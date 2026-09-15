"""F5 — Metrik Dashboard intra-DB (Unit & Bengkel).

Desain (keputusan bersama owner):
1. Rumus angka TETAP di backend (satu sumber kebenaran, konsisten dengan chat):
   - Profit bengkel (proxy, jelas dilabeli) = grandtotal - discount.
   - Profit UNIT ditunda: komponen HP tumpang tindih (hpunit ~= hpdpp+hpppn)
     dan avg hjakhir < avg modal yang mana pun — metrik `nilai_unit`
     menyajikan komponen apa adanya; rumus final menunggu akuntansi dealer.
2. Nama tabel/kolom TIDAK di-hardcode ke query — diambil dari PROFIL
   (`PROFIL_OTOBITZ`) + deteksi kemampuan terhadap `schema_config_json`
   tenant. Tenant yang tabelnya tidak ada -> metrik `unavailable`
   (degradasi anggun, bukan 500). Struktur siap untuk antar-DB (fan-out)
   nanti: fungsi menerima pool+skema per tenant.
3. Semua SQL: single SELECT read-only berparameter ($1..$n), dieksekusi
   lewat `execute_tenant_query` (gerbang #6: transaksi READ ONLY + timeout
   10 dtk + cap baris). Verifier penuh (gerbang #1-#5) SENGAJA tidak dipakai:
   ia mengasumsikan SQL buatan LLM yang tak dipercaya (melarang FILTER,
   ANY, dan JOIN tanpa FK deklarasi — ketiganya dipakai metrik ini di DB
   legacy tanpa FK fisik). Keamanan diganti oleh: SQL 100% tetap dari kode
   (review + test), input user (tanggal/cabang) HANYA masuk via params
   asyncpg (tak pernah interpolasi string), dan eksekusi tetap terkurung.
4. Filter: rentang tanggal (wajib) + daftar kode_cabang (kosong = semua).

Semua fungsi builder di sini MURNI (tanpa I/O) agar mudah di-test.
"""
import logging

from app.services.query_executor import execute_tenant_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Profil Otobitz (satu-satunya profil saat ini)
# ---------------------------------------------------------------------------
PROFIL_OTOBITZ = {
    "penjualan": "untt_penjualan",
    "spk": "untt_pesanankendaraan",
    "kendaraan": "untt_datakendaraan",
    "tipe": "untm_tipe",
    "wo": "srvt_wo",
    "wodetail": "srvt_wodetail",
    "faktur": "srvt_faktur",
    "stockparts": "srvt_stockparts",
    "stockbahan": "srvt_stockbahan",
    "partsmaster": "srvm_parts",
    "accessories": "untt_pesananaccessories",
    "piutang_view": "srv_vw_daftarumurpiutang",
    "hutang_view": "srv_vw_daftarumurhutang",
    "cabang_master": "glbm_cabang",
}

# Komponen nilai unit untuk transparansi (BUKAN profit final).
# Temuan 2026-09-10 di backup_demo_otobitzcloud: hpunit ~= hpdpp + hpppn
# (komponen tumpang tindih) dan avg hjakhir (199 jt) < avg hpunit (244 jt),
# sehingga profit = hjakhir - SUM(HP) negatif dan SALAH. Rumus profit final
# menunggu konfirmasi akuntansi dealer — metrik ini menyajikan komponennya
# apa adanya agar tidak ada angka klaim yang menyesatkan.
_KOMPONEN_NILAI_HP = ["hpunit", "hpdpp", "hpppn", "hppbm", "hpbbn"]

# Batas baris aman per metrik (kecil: agregasi, bukan dump).
_CAP_AGREGAT = 100


# ---------------------------------------------------------------------------
# Helper murni
# ---------------------------------------------------------------------------
def _ada(tables: dict, nama: str) -> bool:
    return isinstance(tables, dict) and nama in tables


def _ada_kolom(tables: dict, tabel: str, kolom: str) -> bool:
    try:
        cols = tables[tabel].get("columns") or []
        return any(c.get("name") == kolom for c in cols)
    except (KeyError, AttributeError, TypeError):
        return False


def deteksi_kemampuan(schema_config: dict, profil: dict = PROFIL_OTOBITZ) -> dict:
    """Metrik apa saja yang bisa dihitung dari skema tenant ini."""
    tables = (schema_config or {}).get("tables") or {}
    ada_spk = _ada(tables, profil["spk"])
    ada_jual = _ada(tables, profil["penjualan"])
    ada_kend = _ada(tables, profil["kendaraan"])
    ada_tipe = _ada(tables, profil["tipe"])
    ada_wo = _ada(tables, profil["wo"])
    ada_faktur = _ada(tables, profil["faktur"])
    ada_stock = _ada(tables, profil["stockparts"])
    ada_piutang = _ada(tables, profil["piutang_view"])
    ada_hutang = _ada(tables, profil["hutang_view"])
    ada_cabang = _ada_kolom(tables, profil["penjualan"], "kode_cabang")
    nilai_lengkap = ada_kend and all(
        _ada_kolom(tables, profil["kendaraan"], k) for k in ("hpunit", "hpdpp", "hjakhir")
    )
    return {
        "spk": ada_spk,
        "penjualan": ada_jual,
        "nilai_unit": ada_jual and nilai_lengkap,
        "top_tipe": ada_jual and ada_kend and ada_tipe,
        "leasing": ada_spk and _ada_kolom(tables, profil["spk"], "kode_bank"),
        "cross_sell": _ada(tables, profil["accessories"]),
        "wo": ada_wo,
        "faktur": ada_faktur,
        "profit_bengkel": ada_faktur and _ada_kolom(tables, profil["faktur"], "discount"),
        "stock": ada_stock,
        "ar_aging": ada_piutang,
        "ap_aging": ada_hutang,
        "filter_cabang": ada_cabang,
    }


def _klausa_cabang(param_idx: int) -> str:
    """Filter kode_cabang multi-item; daftar kosong (NULL) = semua cabang.

    Cast ::text[] eksplisit: asyncpg tidak bisa menebak tipe $n saat nilainya
    NULL (AmbiguousParameterError) — kode_cabang varchar dibanding text[] aman.
    """
    return (f"(${param_idx}::text[] IS NULL "
            f"OR kode_cabang = ANY(${param_idx}::text[]))")


def _rentang(param_tgl: str, dari_idx: int, sampai_idx: int) -> str:
    return f"({param_tgl} >= ${dari_idx}::date AND {param_tgl} < ${sampai_idx}::date)"


# ---------------------------------------------------------------------------
# Builder SQL Unit (murni: kembalikan (sql, params))
# ---------------------------------------------------------------------------
def sql_spk_ringkasan(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    t = profil["spk"]
    sql = (
        f"SELECT count(*) AS total, "
        f"count(*) FILTER (WHERE batal) AS batal, "
        f"count(*) FILTER (WHERE NOT coalesce(batal, false) "
        f"AND coalesce(jumlahpenjualan, 0) = 0) AS outstanding "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)}"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_spk_bulanan(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    t = profil["spk"]
    sql = (
        f"SELECT to_char(tanggal, 'YYYY-MM') AS bulan, count(*) AS total "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)} GROUP BY 1 ORDER BY 1 LIMIT {_CAP_AGREGAT}"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_penjualan_ringkasan(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    t = profil["penjualan"]
    sql = (
        f"SELECT count(*) FILTER (WHERE NOT coalesce(batal, false)) AS unit, "
        f"coalesce(sum(hjakhir) FILTER (WHERE NOT coalesce(batal, false)), 0) AS omzet, "
        f"coalesce(sum(diskon) FILTER (WHERE NOT coalesce(batal, false)), 0) AS diskon "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)}"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_penjualan_bulanan(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    t = profil["penjualan"]
    sql = (
        f"SELECT to_char(tanggal, 'YYYY-MM') AS bulan, "
        f"count(*) FILTER (WHERE NOT coalesce(batal, false)) AS unit, "
        f"coalesce(sum(hjakhir) FILTER (WHERE NOT coalesce(batal, false)), 0) AS omzet "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)} GROUP BY 1 ORDER BY 1 LIMIT {_CAP_AGREGAT}"
    )
    return sql, [dari, sampai, (cabang or None)]


def _ekspresi_modal(dk: str) -> str:
    bagian = " + ".join(f"coalesce(avg({dk}.{k}), 0)" for k in _KOMPONEN_NILAI_HP)
    return f"({bagian})"


def sql_unit_nilai(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    """Komponen nilai unit (avg) — TRANSPARAN, bukan profit final."""
    p, dk = profil["penjualan"], profil["kendaraan"]
    avg_hp = ", ".join(
        f"coalesce(avg(dk.{k}), 0) AS avg_{k}" for k in _KOMPONEN_NILAI_HP)
    sql = (
        f"SELECT coalesce(sum(p.hjakhir), 0) AS revenue, "
        f"coalesce(avg(p.hjakhir), 0) AS avg_hjakhir, "
        f"coalesce(avg(p.hjunit), 0) AS avg_hjunit, {avg_hp} "
        f"FROM {p} p JOIN {dk} dk ON p.norangka = dk.norangka "
        f"WHERE {_rentang('p.tanggal', 1, 2)} "
        f"AND NOT coalesce(p.batal, false) "
        f"AND {_klausa_cabang(3).replace('kode_cabang', 'p.kode_cabang')}"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_top_tipe(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    p, dk, t = profil["penjualan"], profil["kendaraan"], profil["tipe"]
    sql = (
        f"SELECT t.nama AS tipe, count(*) AS unit "
        f"FROM {p} p JOIN {dk} dk ON p.norangka = dk.norangka "
        f"JOIN {t} t ON dk.kode_tipe = t.kode "
        f"WHERE {_rentang('p.tanggal', 1, 2)} "
        f"AND NOT coalesce(p.batal, false) "
        f"AND {_klausa_cabang(3).replace('kode_cabang', 'p.kode_cabang')} "
        f"GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_top_leasing(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    """Top-3 leasing otomatis + hitungan tunai (kode_bank kosong)."""
    t = profil["spk"]
    sql = (
        f"SELECT nullif(kode_bank, '') AS leasing, count(*) AS total "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND NOT coalesce(batal, false) "
        f"AND {_klausa_cabang(3)} GROUP BY 1 ORDER BY 2 DESC LIMIT 4"
    )
    return sql, [dari, sampai, (cabang or None)]


# ---------------------------------------------------------------------------
# Builder SQL Bengkel (murni)
# ---------------------------------------------------------------------------
def sql_wo_ringkasan(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    t = profil["wo"]
    sql = (
        f"SELECT count(*) FILTER (WHERE NOT coalesce(batal, false)) AS unit_entry, "
        f"count(*) FILTER (WHERE coalesce(batal, false)) AS batal "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)}"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_wo_bulanan(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    t = profil["wo"]
    sql = (
        f"SELECT to_char(tanggal, 'YYYY-MM') AS bulan, "
        f"count(*) FILTER (WHERE NOT coalesce(batal, false)) AS unit_entry "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)} GROUP BY 1 ORDER BY 1 LIMIT {_CAP_AGREGAT}"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_wo_per_sa(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    t = profil["wo"]
    sql = (
        f"SELECT penerima AS sa, "
        f"count(*) FILTER (WHERE NOT coalesce(batal, false)) AS unit_entry, "
        f"count(*) FILTER (WHERE coalesce(batal, false)) AS batal "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)} GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_faktur_ringkasan(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    """Revenue = grandtotal; profit (proxy) = grandtotal - discount."""
    t = profil["faktur"]
    sql = (
        f"SELECT count(*) FILTER (WHERE NOT coalesce(batal, false)) AS faktur, "
        f"coalesce(sum(grandtotal) FILTER (WHERE NOT coalesce(batal, false)), 0) AS revenue, "
        f"coalesce(sum(discount) FILTER (WHERE NOT coalesce(batal, false)), 0) AS discount, "
        f"coalesce(sum(total_jasa) FILTER (WHERE NOT coalesce(batal, false)), 0) AS jasa, "
        f"coalesce(sum(total_parts) FILTER (WHERE NOT coalesce(batal, false)), 0) AS parts "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)}"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_faktur_bulanan(profil: dict, dari: str, sampai: str, cabang: list) -> tuple:
    t = profil["faktur"]
    sql = (
        f"SELECT to_char(tanggal, 'YYYY-MM') AS bulan, "
        f"coalesce(sum(grandtotal) FILTER (WHERE NOT coalesce(batal, false)), 0) AS revenue, "
        f"coalesce(sum(total_jasa) FILTER (WHERE NOT coalesce(batal, false)), 0) AS jasa, "
        f"coalesce(sum(total_parts) FILTER (WHERE NOT coalesce(batal, false)), 0) AS parts "
        f"FROM {t} WHERE {_rentang('tanggal', 1, 2)} "
        f"AND {_klausa_cabang(3)} GROUP BY 1 ORDER BY 1 LIMIT {_CAP_AGREGAT}"
    )
    return sql, [dari, sampai, (cabang or None)]


def sql_stock_menipis(profil: dict, cabang: list, limit: int = 10) -> tuple:
    t = profil["stockparts"]
    lim = max(1, min(int(limit), 50))
    sql = (
        f"SELECT kode_parts, (stockawal + masuk - keluar) AS sisa "
        f"FROM {t} WHERE {_klausa_cabang(1)} "
        f"ORDER BY 2 ASC LIMIT {lim}"
    )
    return sql, [(cabang or None)]


def sql_ar_aging(profil: dict, cabang: list) -> tuple:
    v = profil["piutang_view"]
    sql = (
        f"SELECT coalesce(sum(belumjt), 0) AS belum_jt, "
        f"coalesce(sum(jtsampai30), 0) AS jt30, "
        f"coalesce(sum(jtsampai60), 0) AS jt60, "
        f"coalesce(sum(jtsampai90), 0) AS jt90, "
        f"coalesce(sum(jtlebih90), 0) AS jt_lebih90 "
        f"FROM {v} WHERE {_klausa_cabang(1)}"
    )
    return sql, [(cabang or None)]


def sql_ap_aging(profil: dict, cabang: list) -> tuple:
    v = profil["hutang_view"]
    sql = (
        f"SELECT coalesce(sum(belumjt), 0) AS belum_jt, "
        f"coalesce(sum(jtsampai30), 0) AS jt30, "
        f"coalesce(sum(jtsampai60), 0) AS jt60, "
        f"coalesce(sum(jtsampai90), 0) AS jt90, "
        f"coalesce(sum(jtlebih90), 0) AS jt_lebih90 "
        f"FROM {v} WHERE {_klausa_cabang(1)}"
    )
    return sql, [(cabang or None)]


def sql_daftar_cabang(profil: dict) -> tuple:
    """Daftar kode_cabang + label dari master (untuk filter multi-item)."""
    sql = (
        f"SELECT kode AS kode, nama AS nama FROM {profil['cabang_master']} "
        f"ORDER BY 1 LIMIT {_CAP_AGREGAT}"
    )
    return sql, []


# ---------------------------------------------------------------------------
# Runner: jalankan satu metrik lewat gerbang penuh, degradasi anggun bila gagal
# ---------------------------------------------------------------------------
async def jalankan_metrik(pool, schema_config: dict, nama: str,
                          sql: str, params: list) -> dict:
    """Return {ok, columns, rows, sql} — ok=False bila DB error (degradasi).

    Jalur eksekusi: gerbang #6 langsung (lihat alasan di docstring modul).
    `schema_config` diterima agar signature siap untuk verifier bila suatu
    saat profil mengizinkan konstruksi ini (dan untuk antar-DB fan-out).
    """
    try:
        res = await execute_tenant_query(pool, sql, params=params,
                                         row_cap=_CAP_AGREGAT)
    except Exception as e:  # timeout/koneksi — degradasi, bukan 500 buta
        logger.warning("dashboard metrik %s gagal eksekusi: %s", nama, e)
        raise
    kolom = res.get("columns") or []
    baris = [dict(zip(kolom, r)) for r in (res.get("rows") or [])]
    return {"ok": True, "nama": nama, "rows": baris, "sql": sql}
