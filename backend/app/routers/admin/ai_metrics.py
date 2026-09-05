"""Router Admin untuk Analitik Utilisasi AI & Pemantauan Kuota Token Cabang.

Menyajikan metrik performa AI:
- Overview (total query, success rate, estimasi token, penghematan memory replay)
- Timeline tren kueri & efisiensi token
- Pemantauan utilisasi kuota harian per-cabang
- Pengaturan kuota token cabang oleh Administrator
"""
import logging
from datetime import date, timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import get_core_pool
from app.core.security import require_admin_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/ai-metrics", tags=["Admin - AI Metrics & Quotas"])


class UpdateQuotaRequest(BaseModel):
    daily_token_quota: int = Field(..., ge=1000, le=5_000_000, description="Batas kuota token harian cabang (1.000 s/d 5.000.000)")


@router.get("/overview")
async def get_ai_metrics_overview(user: dict = Depends(require_admin_role)) -> dict[str, Any]:
    """Ringkasan metrik global aktivitas kueri AI dan efisiensi sistem."""
    pool = await get_core_pool()

    row = await pool.fetchrow("""
        SELECT
            COUNT(*) AS total_queries,
            COUNT(*) FILTER (WHERE status = 'success') AS total_success,
            COUNT(*) FILTER (WHERE status = 'error') AS total_error,
            COUNT(*) FILTER (WHERE status = 'rejected') AS total_rejected,
            COUNT(*) FILTER (
                WHERE status = 'success' AND (
                    ai_json_filter->'trace'->>'memory_lookup' = 'HIT'
                    OR ai_json_filter->>'source' = 'memory'
                )
            ) AS memory_hits,
            COUNT(*) FILTER (
                WHERE created_at >= CURRENT_DATE AND status = 'success'
            ) AS today_success,
            COUNT(*) FILTER (
                WHERE created_at >= CURRENT_DATE
            ) AS today_total,
            COALESCE(AVG(execution_time_ms) FILTER (WHERE execution_time_ms IS NOT NULL AND status = 'success'), 0) AS avg_latency_ms
        FROM audit_logs
    """)

    total_queries = row["total_queries"] if row else 0
    total_success = row["total_success"] if row else 0
    total_error = row["total_error"] if row else 0
    total_rejected = row["total_rejected"] if row else 0
    memory_hits = row["memory_hits"] if row else 0
    today_total = row["today_total"] if row else 0
    today_success = row["today_success"] if row else 0
    avg_latency = round(float(row["avg_latency_ms"]), 1) if row else 0.0

    # Estimasi perhitungan token
    # Query non-memory yang sukses rata-rata mengonsumsi ~650 token (prompt padat + completion plan/SQL)
    llm_queries = max(0, total_success - memory_hits)
    tokens_estimated = llm_queries * 650

    # Penghematan dari SQL Memory (0-cost replay: rata-rata 1.500 token yang berhasil dihindari per putar-ulang)
    tokens_saved = memory_hits * 1500

    success_rate = round((total_success / total_queries * 100), 1) if total_queries > 0 else 100.0

    return {
        "total_queries": total_queries,
        "total_success": total_success,
        "total_error": total_error,
        "total_rejected": total_rejected,
        "memory_hits": memory_hits,
        "llm_queries": llm_queries,
        "tokens_estimated": tokens_estimated,
        "tokens_saved": tokens_saved,
        "today_total": today_total,
        "today_success": today_success,
        "avg_latency_ms": avg_latency,
        "success_rate": success_rate,
    }


@router.get("/timeline")
async def get_ai_metrics_timeline(
    days: int = Query(7, ge=1, le=90, description="Jumlah hari ke belakang"),
    user: dict = Depends(require_admin_role)
) -> dict[str, Any]:
    """Data deret waktu harian untuk grafik tren kueri dan penggunaan token."""
    pool = await get_core_pool()

    start_date = date.today() - timedelta(days=days - 1)

    rows = await pool.fetch("""
        SELECT
            DATE(created_at) AS query_date,
            COUNT(*) AS total_queries,
            COUNT(*) FILTER (WHERE status = 'success') AS success_queries,
            COUNT(*) FILTER (
                WHERE status = 'success' AND (
                    ai_json_filter->'trace'->>'memory_lookup' = 'HIT'
                    OR ai_json_filter->>'source' = 'memory'
                )
            ) AS memory_hits,
            COUNT(*) FILTER (
                WHERE status = 'success' AND (
                    ai_json_filter->'trace'->>'memory_lookup' = 'MISS'
                    OR ai_json_filter->'trace'->>'memory_lookup' IS NULL
                )
            ) AS llm_queries
        FROM audit_logs
        WHERE created_at >= $1::date
        GROUP BY DATE(created_at)
        ORDER BY query_date ASC
    """, start_date)

    data_map = {r["query_date"]: r for r in rows}

    # Generate complete timeline including days with 0 queries
    timeline = []
    curr = start_date
    end = date.today()

    while curr <= end:
        r = data_map.get(curr)
        total = r["total_queries"] if r else 0
        success = r["success_queries"] if r else 0
        mem = r["memory_hits"] if r else 0
        llm = r["llm_queries"] if r else 0
        est_tokens = llm * 650
        saved_tokens = mem * 1500

        timeline.append({
            "date": curr.isoformat(),
            "formatted_date": curr.strftime("%d %b"),
            "total_queries": total,
            "success_queries": success,
            "memory_hits": mem,
            "llm_queries": llm,
            "estimated_tokens": est_tokens,
            "saved_tokens": saved_tokens,
        })
        curr += timedelta(days=1)

    return {
        "days": days,
        "timeline": timeline,
    }


@router.get("/branch-usage")
async def get_branch_usage(user: dict = Depends(require_admin_role)) -> dict[str, Any]:
    """Status utilisasi kuota token harian per cabang dealer."""
    pool = await get_core_pool()

    rows = await pool.fetch("""
        SELECT
            t.branch_code,
            COALESCE(b.name, t.branch_code) AS branch_name,
            COALESCE(c.name, '-') AS company_name,
            COALESCE(t.daily_token_quota, 50000) AS daily_token_quota,
            t.is_active,
            (
                SELECT COUNT(*)
                FROM audit_logs al
                WHERE al.branch_code = t.branch_code
                  AND al.created_at >= CURRENT_DATE
                  AND al.status = 'success'
                  AND (
                      al.ai_json_filter->'trace'->>'memory_lookup' = 'MISS'
                      OR al.ai_json_filter->'trace'->>'memory_lookup' IS NULL
                  )
            ) AS today_llm_queries,
            (
                SELECT COUNT(*)
                FROM audit_logs al
                WHERE al.branch_code = t.branch_code
                  AND al.created_at >= CURRENT_DATE
            ) AS today_total_queries,
            (
                SELECT COUNT(*)
                FROM audit_logs al
                WHERE al.branch_code = t.branch_code
            ) AS all_time_queries,
            (
                SELECT MAX(al.created_at)
                FROM audit_logs al
                WHERE al.branch_code = t.branch_code
            ) AS last_active_at
        FROM tenants t
        LEFT JOIN branches b ON b.code = t.branch_code
        LEFT JOIN companies c ON c.code = b.company_code
        ORDER BY t.branch_code ASC
    """)

    branches = []
    for r in rows:
        quota = r["daily_token_quota"]
        today_llm = r["today_llm_queries"] or 0
        today_tokens_used = today_llm * 500  # Standar 500 token/query sesuai _cek_kuota_token
        pct = round((today_tokens_used / quota * 100), 1) if quota > 0 else 0.0

        if pct >= 100.0:
            status = "exceeded"
        elif pct >= 85.0:
            status = "critical"
        elif pct >= 65.0:
            status = "warning"
        else:
            status = "ok"

        branches.append({
            "branch_code": r["branch_code"],
            "branch_name": r["branch_name"],
            "company_name": r["company_name"],
            "daily_token_quota": quota,
            "today_tokens_used": today_tokens_used,
            "today_llm_queries": today_llm,
            "today_total_queries": r["today_total_queries"] or 0,
            "all_time_queries": r["all_time_queries"] or 0,
            "quota_percentage": pct,
            "status": status,
            "is_active": r["is_active"],
            "last_active_at": r["last_active_at"].isoformat() if r["last_active_at"] else None,
        })

    return {"branches": branches}


@router.patch("/branch-quota/{branch_code}")
async def update_branch_quota(
    branch_code: str,
    payload: UpdateQuotaRequest,
    user: dict = Depends(require_admin_role),
) -> dict[str, Any]:
    """Memperbarui batas kuota token harian untuk cabang tertentu."""
    pool = await get_core_pool()

    existing = await pool.fetchrow(
        "SELECT branch_code FROM tenants WHERE branch_code = $1",
        branch_code
    )
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Cabang/tenant dengan kode '{branch_code}' tidak ditemukan"
        )

    await pool.execute(
        """
        UPDATE tenants
        SET daily_token_quota = $1, updated_at = CURRENT_TIMESTAMP
        WHERE branch_code = $2
        """,
        payload.daily_token_quota,
        branch_code
    )

    logger.info("Admin %s mengubah kuota token cabang %s menjadi %d",
                user.get("username"), branch_code, payload.daily_token_quota)

    return {
        "success": True,
        "branch_code": branch_code,
        "daily_token_quota": payload.daily_token_quota,
        "message": f"Kuota token harian cabang '{branch_code}' berhasil diperbarui menjadi {payload.daily_token_quota:,} token.",
    }
