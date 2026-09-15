"""F5 — Router dashboard user (intra-DB): /dashboard/unit + /dashboard/bengkel.

Guard sama dengan chat (routers/chat.py):
1. `require_user_role` — hanya role 'user'.
2. `branch_code` WAJIB anggota `allowed_branches` token (isolasi cabang).
3. Koneksi tenant WAJIB lewat `tenant_pool` (interface tunggal).
4. Tiap metrik lewat `verify_and_execute` (gerbang #1-#6); metrik yang
   tabelnya tidak ada di tenant ini -> `available=False` (degradasi anggun).

Catatan antar-DB (fase 2): fungsi di sini menerima pool+skema per tenant,
sehingga fan-out lintas tenant tinggal memanggil runner yang sama per
tenant lalu menggabungkan — tidak perlu mengubah builder SQL.
"""
import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import get_core_pool
from app.core.security import require_user_role
from app.services import dashboard_metrics as dm
from app.services.chat_pipeline import (
    SkemaTidakTersedia, TenantTidakAda, _parse_schema_config, resolve_tenant)
from app.services.tenant_pool import TenantPoolError, get_tenant_pool_manager
from app.routers.chat import cek_rate_limit
import asyncpg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Batas konkurensi metrik paralel per request: 8 metrik × gather tanpa rem
# membuat 1 request dashboard menyedot pool tenant (max 10) dan membuat
# kueri chat antre. 4 paralel cukup (pengukuran: ~1,5 dtk tetap).
_SEMAPHORE_METRIK = asyncio.Semaphore(4)


def _cek_akses(user: dict, branch_code: str) -> None:
    allowed = user.get("allowed_branches") or []
    if branch_code not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Cabang '{branch_code}' bukan penugasan Anda.")


def _parse_tanggal(nama: str, nilai: str) -> date:
    """Validasi YYYY-MM-DD -> date (asyncpg butuh objek date, bukan string)."""
    try:
        y, m, d = (int(x) for x in nilai.split("-"))
        return date(y, m, d)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail=f"Parameter '{nama}' harus format YYYY-MM-DD.")


def _parse_cabang(cabang: Optional[str]) -> list:
    if not cabang:
        return []
    return [k.strip() for k in cabang.split(",") if k.strip()][:20]


async def _konteks_tenant(branch_code: str):
    """(pool tenant, schema_config, kemampuan) atau raise HTTP yang sesuai."""
    core_pool = await get_core_pool()
    try:
        tenant = await resolve_tenant(core_pool, branch_code)
    except TenantTidakAda as e:
        raise HTTPException(status_code=409, detail=str(e))
    try:
        pool = await get_tenant_pool_manager().get_pool(tenant)
    except TenantPoolError as e:
        raise HTTPException(
            status_code=503, detail=f"Database tenant tidak tersedia: {e}")
    try:
        schema = _parse_schema_config(tenant.get("schema_config_json"))
    except SkemaTidakTersedia as e:
        raise HTTPException(status_code=409, detail=str(e))
    return pool, schema, dm.deteksi_kemampuan(schema)


@router.get("/cabang")
async def daftar_cabang(branch_code: str = Query(min_length=1, max_length=50),
                        user: dict = Depends(require_user_role)):
    """Opsi filter cabang intra-DB (kode + label master)."""
    _cek_akses(user, branch_code)
    cek_rate_limit(user["user_id"])
    pool, schema, mampu = await _konteks_tenant(branch_code)
    tables = (schema or {}).get("tables") or {}
    if dm.PROFIL_OTOBITZ["cabang_master"] not in tables:
        return {"cabang": [{"kode": branch_code, "nama": branch_code}]}
    sql, params = dm.sql_daftar_cabang(dm.PROFIL_OTOBITZ)
    hasil = await dm.jalankan_metrik(pool, schema, "cabang", sql, params)
    if not hasil.get("ok"):
        return {"cabang": [{"kode": branch_code, "nama": branch_code}]}
    return {"cabang": hasil["rows"]}


async def _satu_metrik(pool, schema, branch_code: str, profil: dict,
                     mampu: dict, nama: str, syarat: str, builder,
                     dari: date, sampai: date, cabang: list) -> tuple:
    """Satu metrik -> (nama, hasil); aman diparalel via gather (pool asyncpg
    melayani banyak koneksi sekaligus). Gagal satu != gagal semua."""
    if syarat and not mampu.get(syarat):
        return nama, {"ok": False, "available": False,
                      "alasan": "tidak_tersedia_di_db_ini"}
    try:
        sql, params = builder(profil, dari, sampai, cabang)
    except TypeError:
        sql, params = builder(profil, cabang)
    try:
        async with _SEMAPHORE_METRIK:
            hasil = await dm.jalankan_metrik(pool, schema, nama, sql, params)
    except asyncpg.exceptions.QueryCanceledError:
        hasil = {"ok": False, "nama": nama, "alasan": "timeout_10_detik"}
    except Exception as e:
        logger.warning("dashboard %s metrik %s gagal: %s",
                       branch_code, nama, e)
        hasil = {"ok": False, "nama": nama, "alasan": "eksekusi_gagal"}
    # available=True HANYA bila sukses; SQL internal tak pernah ke role user.
    hasil["available"] = bool(hasil.get("ok"))
    hasil.pop("sql", None)
    return nama, hasil


async def _ringkasan(branch_code: str, dari: str, sampai: str, cabang: list,
                     paket: list) -> dict:
    """Jalankan paket [(nama, butuh_mampu, builder)] PARALEL -> {metrik}.

    Sebelumnya berurutan (~4-5 dtk per endpoint); gather memangkas ke
    metrik terlambat saja. Pool tenant melayani konkurensi dengan aman.
    """
    pool, schema, mampu = await _konteks_tenant(branch_code)
    profil = dm.PROFIL_OTOBITZ
    hasil = await asyncio.gather(*(
        _satu_metrik(pool, schema, branch_code, profil, mampu, nama, syarat,
                     builder, dari, sampai, cabang)
        for nama, syarat, builder in paket
    ))
    return {"branch_code": branch_code, "dari": dari, "sampai": sampai,
            "cabang": cabang, "kemampuan": mampu, "metrik": dict(hasil)}


@router.get("/unit")
async def dashboard_unit(
        branch_code: str = Query(min_length=1, max_length=50),
        dari: str = Query(description="YYYY-MM-DD awal (inklusif)"),
        sampai: str = Query(description="YYYY-MM-DD akhir (eksklusif)"),
        cabang: Optional[str] = Query(default=None,
                                      description="kode_cabang koma, kosong = semua"),
        user: dict = Depends(require_user_role)):
    """Ringkasan Unit: SPK, penjualan, revenue/profit, top tipe, leasing, AR."""
    _cek_akses(user, branch_code)
    cek_rate_limit(user["user_id"])
    d1, d2 = _parse_tanggal("dari", dari), _parse_tanggal("sampai", sampai)
    if d1 >= d2:
        raise HTTPException(status_code=400,
                            detail="'dari' harus lebih awal dari 'sampai'.")
    daftar = _parse_cabang(cabang)
    paket = [
        ("spk", "spk", dm.sql_spk_ringkasan),
        ("spk_bulanan", "spk", dm.sql_spk_bulanan),
        ("penjualan", "penjualan", dm.sql_penjualan_ringkasan),
        ("penjualan_bulanan", "penjualan", dm.sql_penjualan_bulanan),
        ("nilai_unit", "nilai_unit", dm.sql_unit_nilai),
        ("top_tipe", "top_tipe", dm.sql_top_tipe),
        ("top_leasing", "leasing", dm.sql_top_leasing),
        ("ar_aging", "ar_aging", dm.sql_ar_aging),
    ]
    return await _ringkasan(branch_code, d1, d2, daftar, paket)


@router.get("/bengkel")
async def dashboard_bengkel(
        branch_code: str = Query(min_length=1, max_length=50),
        dari: str = Query(description="YYYY-MM-DD awal (inklusif)"),
        sampai: str = Query(description="YYYY-MM-DD akhir (eksklusif)"),
        cabang: Optional[str] = Query(default=None,
                                      description="kode_cabang koma, kosong = semua"),
        user: dict = Depends(require_user_role)):
    """Ringkasan Bengkel: WO, faktur revenue/profit, SA, stock, AR/AP aging."""
    _cek_akses(user, branch_code)
    cek_rate_limit(user["user_id"])
    d1, d2 = _parse_tanggal("dari", dari), _parse_tanggal("sampai", sampai)
    if d1 >= d2:
        raise HTTPException(status_code=400,
                            detail="'dari' harus lebih awal dari 'sampai'.")
    daftar = _parse_cabang(cabang)
    paket = [
        ("wo", "wo", dm.sql_wo_ringkasan),
        ("wo_bulanan", "wo", dm.sql_wo_bulanan),
        ("wo_per_sa", "wo", dm.sql_wo_per_sa),
        ("faktur", "faktur", dm.sql_faktur_ringkasan),
        ("faktur_bulanan", "faktur", dm.sql_faktur_bulanan),
        ("stock_menipis", "stock", dm.sql_stock_menipis),
        ("ar_aging", "ar_aging", dm.sql_ar_aging),
        ("ap_aging", "ap_aging", dm.sql_ap_aging),
    ]
    return await _ringkasan(branch_code, d1, d2, daftar, paket)
