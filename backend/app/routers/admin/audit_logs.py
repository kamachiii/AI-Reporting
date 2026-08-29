"""Endpoint audit log — query riwayat query AI user."""
import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import get_core_pool
from app.core.security import require_admin_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Audit Logs"])


@router.get("/audit-logs")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=10, le=100),
    status: str | None = Query(None),
    q: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user: dict = Depends(require_admin_role),
):
    # asyncpg menolak string utk parameter ::date — parse & validasi di sini
    try:
        parsed_from = date.fromisoformat(date_from) if date_from else None
        parsed_to = date.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Filter tanggal harus format YYYY-MM-DD")

    pool = await get_core_pool()
    where = []
    params = []
    idx = 1

    if status:
        where.append(f"al.status = ${idx}")
        params.append(status)
        idx += 1
    if q:
        like = f"%{q}%"
        where.append(
            f"(u.username ILIKE ${idx} OR al.branch_code ILIKE ${idx} "
            f"OR COALESCE(al.prompt_text, '') ILIKE ${idx})"
        )
        params.append(like)
        idx += 1
    if parsed_from:
        where.append(f"al.created_at >= ${idx}::date")
        params.append(parsed_from)
        idx += 1
    if parsed_to:
        where.append(f"al.created_at < (${idx}::date + interval '1 day')")
        params.append(parsed_to)
        idx += 1

    where_clause = "WHERE " + " AND ".join(where) if where else ""

    # JOIN users ikut dihitung agar filter q (username) konsisten dengan data query
    count_sql = (
        f"SELECT COUNT(*) FROM audit_logs al "
        f"LEFT JOIN users u ON u.id = al.user_id {where_clause}"
    )
    total = await pool.fetchval(count_sql, *params)

    offset = (page - 1) * per_page
    data_sql = f"""
        SELECT al.id, al.user_id, al.branch_code, al.prompt_text,
               al.ai_json_filter, al.generated_sql, al.execution_time_ms,
               al.status, al.error_message, al.created_at,
               u.username AS user_name
        FROM audit_logs al
        LEFT JOIN users u ON u.id = al.user_id
        {where_clause}
        ORDER BY al.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    rows = await pool.fetch(data_sql, *params, per_page, offset)

    return {
        "data": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }