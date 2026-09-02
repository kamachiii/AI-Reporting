"""Endpoints admin untuk Eval Harness Golden-Set (F2.7, docs v2 §6/§8).

Golden set per tenant (tabel `eval_cases`, migration 009):
- GET    /admin/tenants/{branch_code}/eval-cases          — daftar kasus
- POST   /admin/tenants/{branch_code}/eval-cases          — tambah kasus
- PUT    /admin/tenants/{branch_code}/eval-cases/{id}     — edit kasus
- DELETE /admin/tenants/{branch_code}/eval-cases/{id}     — hapus kasus

sql_harapan WAJIB lolos verifier (sql_guard.verify_sql) terhadap skema
EFEKTIF tenant (KB tabel_diizinkan/tabel_dilarang/kolom_dikecualikan) —
golden set yang salah tidak boleh masuk (422 gate+reason).

Eksekusi eval + riwayat (tabel `eval_runs`, migration 010):
- POST /admin/tenants/{branch_code}/eval-run          — jalankan eval
    (memanggil LLM nyata per kasus; parameter query `batas` membatasi
    jumlah kasus) lalu simpan snapshot metrik + ter-audit.
- GET  /admin/tenants/{branch_code}/eval-runs?limit=5 — riwayat snapshot.

Semua endpoint di-guard `require_admin_role` (pola router admin lain) dan
ter-audit via tulis_audit (sukses maupun penolakan — pola tenants.py).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.database import get_core_pool
from app.core.security import require_admin_role
from app.services.chat_pipeline import TenantTidakAda, resolve_tenant, \
    tulis_audit
from app.services.eval_runner import (
    ambil_run_terakhir, jalankan_eval, simpan_metrik, status_gate,
    verifikasi_sql_harapan)
from app.services.tenant_pool import get_tenant_pool_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Eval Harness"])


class EvalCaseCreate(BaseModel):
    pertanyaan: str
    sql_harapan: str
    catatan: str | None = None


class EvalCaseUpdate(BaseModel):
    pertanyaan: str | None = None
    sql_harapan: str | None = None
    catatan: str | None = None
    aktif: bool | None = None


_KOLOM_CASE = ("id, pertanyaan, sql_harapan, catatan, aktif, "
               "created_at, updated_at")


def _case_response(row) -> dict:
    """Baris eval_cases -> bentuk response (timestamp ISO string)."""
    return {
        "id": row["id"],
        "pertanyaan": row["pertanyaan"],
        "sql_harapan": row["sql_harapan"],
        "catatan": row["catatan"],
        "aktif": row["aktif"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def _audit(pool, user, branch_code: str, aksi: str, status: str,
                 pesan: str | None = None, extra: dict | None = None) -> None:
    """Audit operasi eval (pola tulis_audit chat_pipeline)."""
    try:
        await tulis_audit(
            pool, user_id=(user or {}).get("user_id"), branch_code=branch_code,
            prompt_text=f"[eval-{aksi}] {branch_code}",
            ai_json_filter=extra, generated_sql=None, execution_time_ms=None,
            status=status, error_message=pesan)
    except Exception as e:  # audit tidak pernah menggagalkan operasi
        logger.error("eval router: gagal menulis audit: %s", e)


async def _resolve_tenant_atau_404(pool, branch_code: str) -> dict:
    """Tenant utk cabang admin; TenantTidakAda -> 404 (konteks admin)."""
    try:
        return await resolve_tenant(pool, branch_code)
    except TenantTidakAda as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===========================================================================
# CRUD eval-cases
# ===========================================================================
@router.get("/tenants/{branch_code}/eval-cases")
async def get_eval_cases(branch_code: str,
                         user: dict = Depends(require_admin_role)):
    """Daftar pertanyaan emas (golden set) milik tenant cabang ini."""
    try:
        pool = await get_core_pool()
        tenant = await _resolve_tenant_atau_404(pool, branch_code)
        rows = await pool.fetch(
            f"SELECT {_KOLOM_CASE} FROM eval_cases WHERE tenant_id = $1 "
            "ORDER BY id", tenant["tenant_id"])
        return [_case_response(r) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching eval cases {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/tenants/{branch_code}/eval-cases")
async def create_eval_case(branch_code: str, payload: EvalCaseCreate,
                           user: dict = Depends(require_admin_role)):
    """Tambah pertanyaan emas. sql_harapan diverifikasi dulu terhadap skema
    efektif — verifier menolak = 422 (golden set yang salah tidak masuk)."""
    try:
        pool = await get_core_pool()
        tenant = await _resolve_tenant_atau_404(pool, branch_code)

        pertanyaan = (payload.pertanyaan or "").strip()
        if not pertanyaan:
            raise HTTPException(
                status_code=422, detail={
                    "gate": "bentuk",
                    "reason": "pertanyaan tidak boleh kosong"})
        sql_harapan = (payload.sql_harapan or "").strip()
        if not sql_harapan:
            raise HTTPException(
                status_code=422, detail={
                    "gate": "bentuk",
                    "reason": "sql_harapan tidak boleh kosong"})

        verdict = verifikasi_sql_harapan(tenant, sql_harapan)
        if not verdict["ok"]:
            await _audit(pool, user, branch_code, "case-create", "error",
                         pesan=f"sql_harapan ditolak verifier: "
                               f"{verdict['reason']}",
                         extra={"gate": verdict["gate"]})
            raise HTTPException(status_code=422, detail={
                "gate": verdict["gate"], "reason": verdict["reason"]})

        row = await pool.fetchrow(
            f"INSERT INTO eval_cases (tenant_id, pertanyaan, sql_harapan, "
            f"catatan) VALUES ($1, $2, $3, $4) RETURNING {_KOLOM_CASE}",
            tenant["tenant_id"], pertanyaan, sql_harapan, payload.catatan)
        await _audit(pool, user, branch_code, "case-create", "success",
                     extra={"eval_case_id": row["id"],
                            "pertanyaan": pertanyaan})
        return _case_response(row)
    except HTTPException:
        raise
    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail=f"Pertanyaan emas ini sudah ada untuk cabang "
                       f"{branch_code} (UNIQUE tenant+pertanyaan).")
        logger.error(f"Error creating eval case {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/tenants/{branch_code}/eval-cases/{case_id}")
async def update_eval_case(branch_code: str, case_id: int,
                           payload: EvalCaseUpdate,
                           user: dict = Depends(require_admin_role)):
    """Edit pertanyaan emas (field yang dikirim saja yang berubah)."""
    try:
        pool = await get_core_pool()
        tenant = await _resolve_tenant_atau_404(pool, branch_code)
        lama = await pool.fetchrow(
            f"SELECT {_KOLOM_CASE} FROM eval_cases WHERE id = $1 "
            "AND tenant_id = $2", case_id, tenant["tenant_id"])
        if not lama:
            raise HTTPException(
                status_code=404,
                detail=f"Eval case #{case_id} tidak ditemukan untuk cabang "
                       f"'{branch_code}'.")

        pertanyaan = payload.pertanyaan \
            if payload.pertanyaan is not None else lama["pertanyaan"]
        pertanyaan = (pertanyaan or "").strip()
        if not pertanyaan:
            raise HTTPException(
                status_code=422, detail={
                    "gate": "bentuk",
                    "reason": "pertanyaan tidak boleh kosong"})
        sql_harapan = payload.sql_harapan \
            if payload.sql_harapan is not None else lama["sql_harapan"]
        sql_harapan = (sql_harapan or "").strip()
        catatan = payload.catatan if payload.catatan is not None \
            else lama["catatan"]
        aktif = payload.aktif if payload.aktif is not None else lama["aktif"]

        # Validasi hanya bila teks SQL benar-benar berubah (hemat + idempotent)
        if sql_harapan != lama["sql_harapan"]:
            if not sql_harapan:
                raise HTTPException(
                    status_code=422, detail={
                        "gate": "bentuk",
                        "reason": "sql_harapan tidak boleh kosong"})
            verdict = verifikasi_sql_harapan(tenant, sql_harapan)
            if not verdict["ok"]:
                await _audit(pool, user, branch_code, "case-update", "error",
                             pesan=f"sql_harapan ditolak verifier: "
                                   f"{verdict['reason']}",
                             extra={"eval_case_id": case_id,
                                    "gate": verdict["gate"]})
                raise HTTPException(status_code=422, detail={
                    "gate": verdict["gate"], "reason": verdict["reason"]})

        row = await pool.fetchrow(
            f"UPDATE eval_cases SET pertanyaan = $2, sql_harapan = $3, "
            f"catatan = $4, aktif = $5, updated_at = CURRENT_TIMESTAMP "
            f"WHERE id = $1 AND tenant_id = $6 RETURNING {_KOLOM_CASE}",
            case_id, pertanyaan, sql_harapan, catatan, aktif,
            tenant["tenant_id"])
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Eval case #{case_id} tidak ditemukan untuk cabang "
                       f"'{branch_code}'.")
        await _audit(pool, user, branch_code, "case-update", "success",
                     extra={"eval_case_id": case_id, "aktif": aktif})
        return _case_response(row)
    except HTTPException:
        raise
    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail="Pertanyaan emas baru bertabrakan dengan kasus lain "
                       "(UNIQUE tenant+pertanyaan).")
        logger.error(f"Error updating eval case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/tenants/{branch_code}/eval-cases/{case_id}")
async def delete_eval_case(branch_code: str, case_id: int,
                           user: dict = Depends(require_admin_role)):
    """Hapus pertanyaan emas dari golden set."""
    try:
        pool = await get_core_pool()
        tenant = await _resolve_tenant_atau_404(pool, branch_code)
        result = await pool.execute(
            "DELETE FROM eval_cases WHERE id = $1 AND tenant_id = $2",
            case_id, tenant["tenant_id"])
        if result == "DELETE 0":
            raise HTTPException(
                status_code=404,
                detail=f"Eval case #{case_id} tidak ditemukan untuk cabang "
                       f"'{branch_code}'.")
        await _audit(pool, user, branch_code, "case-delete", "success",
                     extra={"eval_case_id": case_id})
        return {"message": f"Eval case #{case_id} dihapus",
                "id": case_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting eval case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# Eksekusi eval + riwayat + gate
# ===========================================================================
@router.post("/tenants/{branch_code}/eval-run")
async def run_eval(branch_code: str, batas: int | None = Query(default=None,
                           ge=1, description="Maks kasus per run (default "
                           "semua kasus aktif)"),
                   user: dict = Depends(require_admin_role)):
    """Jalankan eval golden-set + simpan snapshot metrik (docs v2 §8).

    Memanggil LLM nyata per kasus (planner/generator) — pakai `batas` untuk
    run kecil. Hasil per kasus: persis / semantik / gagal / pelanggaran;
    baris eval_runs terbaru menjadi dasar gate aktivasi Tier 2.
    """
    pool = None
    try:
        pool = await get_core_pool()
        tenant = await _resolve_tenant_atau_404(pool, branch_code)
        username = (user or {}).get("username") or "admin"
        hasil = await jalankan_eval(
            pool, branch_code, username, batas=batas,
            tenant_pool_manager=get_tenant_pool_manager())
        hasil["dijalankan_oleh"] = username
        ringkas = await simpan_metrik(pool, branch_code, hasil)
        run_terakhir = await ambil_run_terakhir(pool, tenant["tenant_id"])
        gate = status_gate({"branch_code": branch_code}, run_terakhir)
        await _audit(pool, user, branch_code, "run", "success",
                     extra={"run_id": ringkas["run_id"],
                            "total": hasil["total"],
                            "lulus": hasil["lulus"],
                            "pelanggaran_verifier":
                                hasil["pelanggaran_verifier"],
                            "pass_rate": hasil["pass_rate"]})
        return {**ringkas, "gagal": hasil["gagal"], "detail": hasil["detail"],
                "gate": gate}
    except HTTPException:
        raise
    except TenantTidakAda as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error running eval {branch_code}: {e}")
        if pool is not None:
            await _audit(pool, user, branch_code, "run", "error",
                         pesan=str(e)[:500])
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/tenants/{branch_code}/eval-runs")
async def get_eval_runs(branch_code: str, limit: int = Query(default=5, ge=1,
                        le=50),
                        user: dict = Depends(require_admin_role)):
    """Riwayat snapshot eval (terbaru dulu) — metrik mingguan + gate."""
    try:
        pool = await get_core_pool()
        tenant = await _resolve_tenant_atau_404(pool, branch_code)
        rows = await pool.fetch(
            "SELECT id, total, lulus, pelanggaran_verifier, pass_rate, "
            "dijalankan_oleh, created_at FROM eval_runs WHERE tenant_id = $1 "
            "ORDER BY created_at DESC, id DESC LIMIT $2",
            tenant["tenant_id"], limit)
        return [{
            "id": r["id"], "total": r["total"], "lulus": r["lulus"],
            "pelanggaran_verifier": r["pelanggaran_verifier"],
            "pass_rate": float(r["pass_rate"]),
            "dijalankan_oleh": r["dijalankan_oleh"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        } for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching eval runs {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
