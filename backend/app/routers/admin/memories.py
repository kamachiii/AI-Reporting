"""Endpoints admin untuk Kelola SQL Memory (QA2-01).

Latar: jawaban mode Vanna tersimpan otomatis; bila jawaban salah telanjur
approved, tombol chat "Jawaban salah" menolak menurunkannya (doktrin
tidak-pernah-downgrade) sehingga entri salah me-replay selamanya. Satu-satunya
remediasi yang benar adalah penghapusan eksplisit oleh admin — disediakan di
sini, tercatat di audit log.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import get_core_pool
from app.core.security import require_admin_role
from app.services.chat_pipeline import tulis_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - SQL Memory"])


async def _audit(pool, user, branch_code: str, aksi: str, target: str,
                 status: str, detail: str | None = None) -> None:
    """Audit tak pernah menggagalkan operasi (pola eval.py).

    branch_code WAJIB non-null (kolom audit_logs NOT NULL).
    """
    try:
        await tulis_audit(
            pool, user_id=(user or {}).get("user_id"),
            branch_code=branch_code, prompt_text=f"[{aksi}] {target}",
            ai_json_filter={"category": "admin", "aksi": aksi},
            generated_sql=None, execution_time_ms=None,
            status=status, error_message=detail)
    except Exception as e:
        logger.error("audit %s gagal: %s", aksi, e)


@router.get("/memories")
async def list_memories(branch_code: str | None = Query(default=None),
                        status: str | None = Query(default=None),
                        limit: int = Query(default=25, ge=1, le=100),
                        offset: int = Query(default=0, ge=0),
                        user: dict = Depends(require_admin_role)):
    """Daftar entri SQL memory per cabang + status (untuk kurasi admin)."""
    try:
        pool = await get_core_pool()
        conditions = []
        params = []
        idx = 1
        if branch_code:
            conditions.append(f"t.branch_code = ${idx}")
            params.append(branch_code)
            idx += 1
        if status:
            if status not in ("pending", "approved", "rejected", "stale"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Status tidak valid: {status}")
            conditions.append(f"m.status = ${idx}")
            params.append(status)
            idx += 1
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        total = await pool.fetchval(
            f"SELECT COUNT(*) FROM sql_memory m "
            f"JOIN tenants t ON t.id = m.tenant_id {where}", *params)
        rows = await pool.fetch(
            f"SELECT m.id, t.branch_code, m.pertanyaan_ternormalisasi, "
            f"m.sql, m.status, m.sumber, m.times_used, m.updated_at "
            f"FROM sql_memory m JOIN tenants t ON t.id = m.tenant_id "
            f"{where} ORDER BY m.id DESC "
            f"LIMIT ${idx} OFFSET ${idx + 1}", *params, limit, offset)
        return {
            "total": total or 0,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": r["id"],
                    "branch_code": r["branch_code"],
                    "pertanyaan": r["pertanyaan_ternormalisasi"],
                    "sql": r["sql"],
                    "status": r["status"],
                    "sumber": r["sumber"],
                    "times_used": r["times_used"],
                    "updated_at": r["updated_at"].isoformat()
                    if r["updated_at"] else None,
                }
                for r in rows
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing memories: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/memories/{memory_id}/pulihkan")
async def pulihkan_memory(memory_id: int,
                          user: dict = Depends(require_admin_role)):
    """Kembalikan entri `stale` menjadi `pending` (anti false-stale K1).

    Stale yang benar-benar usang akan gagal verifikasi lagi saat replay dan
    kembali stale; yang mati karena transient hidup kembali dan wajib
    dikonfirmasi ulang sebelum approved (tidak ada bypass governance).
    Tercatat di audit.
    """
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow(
            "SELECT m.id, m.status, t.branch_code, m.pertanyaan_ternormalisasi "
            "FROM sql_memory m JOIN tenants t ON t.id = m.tenant_id "
            "WHERE m.id = $1", memory_id)
        if not row:
            await _audit(pool, user, "", "memory-pulihkan", f"#{memory_id}",
                         "error", "Memori tidak ditemukan")
            raise HTTPException(
                status_code=404,
                detail=f"Memori #{memory_id} tidak ditemukan.")
        if row["status"] != "stale":
            raise HTTPException(
                status_code=409,
                detail=f"Hanya status 'stale' yang dapat dipulihkan "
                       f"(status saat ini: '{row['status']}').")
        await pool.execute(
            "UPDATE sql_memory SET status = 'pending', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = $1", memory_id)
        await _audit(
            pool, user, row["branch_code"], "memory-pulihkan",
            f"#{memory_id} [{row['branch_code']}] "
            f"{row['pertanyaan_ternormalisasi']}", "success")
        return {"message": f"Memori #{memory_id} dipulihkan ke 'pending'",
                "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error memulihkan memori %s: %s", memory_id, e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int,
                        user: dict = Depends(require_admin_role)):
    """Hapus permanen satu entri SQL memory yang salah (remediasi QA2-01).

    Tercatat di audit (sukses & gagal-tidak-ditemukan).
    """
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow(
            "SELECT m.id, t.branch_code, m.pertanyaan_ternormalisasi "
            "FROM sql_memory m JOIN tenants t ON t.id = m.tenant_id "
            "WHERE m.id = $1", memory_id)
        if not row:
            await _audit(pool, user, "", "memory-delete", f"#{memory_id}",
                         "error", "Memori tidak ditemukan")
            raise HTTPException(
                status_code=404,
                detail=f"Memori #{memory_id} tidak ditemukan.")
        await pool.execute("DELETE FROM sql_memory WHERE id = $1", memory_id)
        await _audit(
            pool, user, row["branch_code"], "memory-delete",
            f"#{memory_id} [{row['branch_code']}] "
            f"{row['pertanyaan_ternormalisasi']}", "success")
        return {"message": f"Memori #{memory_id} berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting memory %s: %s", memory_id, e)
        raise HTTPException(status_code=500, detail="Internal server error")
