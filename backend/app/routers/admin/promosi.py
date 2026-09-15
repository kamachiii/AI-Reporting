"""Endpoints admin untuk Antrean Promosi KB (governance penyatuan).

Alur: tombol chat "Benar" pertama -> nominasi otomatis (diusulkan) ->
admin setuju (verifikasi SQL + masuk contoh KB tenant) atau tolak.
Kedaluarsa 30 hari dibersihkan malas (lazy) saat list dibaca.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.database import get_core_pool
from app.core.security import require_admin_role
from app.services.chat_pipeline import SkemaTidakTersedia
from app.services.chat_pipeline import tulis_audit as _tulis_audit
from app.services.eval_runner import verifikasi_sql_harapan
from app.services.knowledge_base import parse_stored_kb, validate_kb
from app.services.admin_audit import audit_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Promosi KB"])

_STATUS_VALID = ("diusulkan", "disetujui", "ditolak", "kedaluwarsa")
_BATAS_HARI = 30


async def _audit(pool, user, branch_code: str, aksi: str, target: str,
                 status: str, detail: str | None = None) -> None:
    try:
        await _tulis_audit(
            pool, user_id=(user or {}).get("user_id"),
            branch_code=branch_code or "", prompt_text=f"[{aksi}] {target}",
            ai_json_filter={"category": "admin", "aksi": aksi},
            generated_sql=None, execution_time_ms=None,
            status=status, error_message=detail)
    except Exception as e:
        logger.error("audit %s gagal: %s", aksi, e)


class TolakRequest(BaseModel):
    alasan: str | None = None


def _baris(row) -> dict:
    return {
        "id": row["id"],
        "branch_code": row["branch_code"],
        "memory_id": row["memory_id"],
        "pertanyaan": row["pertanyaan"],
        "sql": row["sql"],
        "status": row["status"],
        "dibuat_oleh": row["dibuat_oleh"],
        "diputus_oleh": row["diputus_oleh"],
        "alasan": row["alasan"],
        "created_at": row["created_at"].isoformat()
        if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat()
        if row["updated_at"] else None,
    }


@router.get("/promosi")
async def list_promosi(branch_code: str | None = Query(default=None),
                       status: str | None = Query(default=None),
                       limit: int = Query(default=25, ge=1, le=100),
                       offset: int = Query(default=0, ge=0),
                       user: dict = Depends(require_admin_role)):
    """Daftar antrean promosi (kedaluwarsa >30 hari ditandai malas)."""
    try:
        pool = await get_core_pool()
        await pool.execute(
            "UPDATE promosi_kb SET status = 'kedaluwarsa', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'diusulkan' AND created_at < "
            "CURRENT_TIMESTAMP - ($1 || ' days')::interval",
            str(_BATAS_HARI))
        conditions = []
        params = []
        idx = 1
        if branch_code:
            conditions.append(f"t.branch_code = ${idx}")
            params.append(branch_code)
            idx += 1
        if status:
            if status not in _STATUS_VALID:
                raise HTTPException(
                    status_code=400, detail=f"Status tidak valid: {status}")
            conditions.append(f"p.status = ${idx}")
            params.append(status)
            idx += 1
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        total = await pool.fetchval(
            f"SELECT COUNT(*) FROM promosi_kb p "
            f"JOIN tenants t ON t.id = p.tenant_id {where}", *params)
        rows = await pool.fetch(
            f"SELECT p.id, t.branch_code, p.memory_id, p.pertanyaan, p.sql, "
            f"p.status, p.dibuat_oleh, p.diputus_oleh, p.alasan, "
            f"p.created_at, p.updated_at FROM promosi_kb p "
            f"JOIN tenants t ON t.id = p.tenant_id {where} "
            f"ORDER BY p.id DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *params, limit, offset)
        return {"total": total or 0, "limit": limit, "offset": offset,
                "items": [_baris(r) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing promosi: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/promosi/{promosi_id}/setuju")
@audit_admin("promosi-setuju", target="promosi_id")
async def setuju_promosi(promosi_id: int,
                         user: dict = Depends(require_admin_role)):
    """Setujui kandidat: verifikasi SQL vs skema tenant, lalu masukkan
    sebagai contoh KB tenant (tenant-scope; global = langkah terpisah).

    Verifikasi gagal -> otomatis ditolak dengan alasan (bukan 500).
    """
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow(
            "SELECT p.*, t.branch_code, t.schema_config_json, "
            "t.knowledge_base FROM promosi_kb p "
            "JOIN tenants t ON t.id = p.tenant_id WHERE p.id = $1",
            promosi_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Promosi #{promosi_id} tidak ditemukan.")
        if row["status"] != "diusulkan":
            raise HTTPException(
                status_code=409,
                detail=f"Promosi #{promosi_id} sudah diputus "
                       f"({row['status']}).")
        tenant_row = {"schema_config_json": row["schema_config_json"],
                      "knowledge_base": row["knowledge_base"]}
        try:
            verdict = verifikasi_sql_harapan(tenant_row, row["sql"])
        except SkemaTidakTersedia as e:
            await pool.execute(
                "UPDATE promosi_kb SET status = 'ditolak', diputus_oleh = $1, "
                "alasan = $2, updated_at = CURRENT_TIMESTAMP WHERE id = $3",
                (user or {}).get("user_id"),
                f"Skema tenant belum tersedia: {e}", promosi_id)
            raise HTTPException(status_code=422, detail={
                "message": "Skema tenant belum tersedia; promosi ditolak",
                "reason": str(e)})
        if not verdict["ok"]:
            await pool.execute(
                "UPDATE promosi_kb SET status = 'ditolak', "
                "diputus_oleh = $1, alasan = $2, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = $3",
                (user or {}).get("user_id"),
                f"Gagal verifikasi skema (gate {verdict['gate']}): "
                f"{verdict['reason']}", promosi_id)
            raise HTTPException(status_code=422, detail={
                "gate": verdict["gate"], "reason": verdict["reason"]})
        kb = parse_stored_kb(row["knowledge_base"])
        contoh = list(kb.get("contoh_tanya") or [])
        tanya_baru = {"tanya": row["pertanyaan"]}
        if tanya_baru not in contoh:
            contoh.append(tanya_baru)
        kb["contoh_tanya"] = contoh
        clean, errors = validate_kb(kb)
        if errors:
            raise HTTPException(status_code=422, detail={
                "message": "KB tenant tidak valid", "errors": errors})
        await pool.execute(
            "UPDATE tenants SET knowledge_base = $2::jsonb, "
            "updated_at = CURRENT_TIMESTAMP WHERE branch_code = $1",
            row["branch_code"], json.dumps(clean))
        await pool.execute(
            "UPDATE promosi_kb SET status = 'disetujui', diputus_oleh = $1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = $2",
            (user or {}).get("user_id"), promosi_id)
        await _audit(pool, user, row["branch_code"], "promosi-setuju",
                     f"#{promosi_id} {row['pertanyaan']}", "success")
        return {"message": f"Promosi #{promosi_id} disetujui. Pola masuk "
                           f"contoh KB {row['branch_code']}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error menyetujui promosi %s: %s", promosi_id, e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/promosi/{promosi_id}/tolak")
@audit_admin("promosi-tolak", target="promosi_id")
async def tolak_promosi(promosi_id: int, payload: TolakRequest,
                        user: dict = Depends(require_admin_role)):
    """Tolak kandidat + tandai pola agar tak diajukan ulang."""
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow(
            "SELECT id, status FROM promosi_kb WHERE id = $1", promosi_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Promosi #{promosi_id} tidak ditemukan.")
        if row["status"] != "diusulkan":
            raise HTTPException(
                status_code=409,
                detail=f"Promosi #{promosi_id} sudah diputus "
                       f"({row['status']}).")
        branch = (await pool.fetchrow(
            "SELECT t.branch_code FROM promosi_kb p "
            "JOIN tenants t ON t.id = p.tenant_id WHERE p.id = $1",
            promosi_id) or {}).get("branch_code", "")
        await pool.execute(
            "UPDATE promosi_kb SET status = 'ditolak', diputus_oleh = $1, "
            "alasan = $2, updated_at = CURRENT_TIMESTAMP WHERE id = $3",
            (user or {}).get("user_id"), payload.alasan, promosi_id)
        await _audit(pool, user, branch, "promosi-tolak",
                     f"#{promosi_id} {payload.alasan or ''}", "success")
        return {"message": f"Promosi #{promosi_id} ditolak"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error menolak promosi %s: %s", promosi_id, e)
        raise HTTPException(status_code=500, detail="Internal server error")
