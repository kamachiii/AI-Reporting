"""Router Admin: Manajemen Vektor & Training AI Instan (pgvector)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import get_core_pool
from app.core.security import require_admin_role
from app.services.vanna_pgvector import (
    cari_konteks_pgvector,
    injeksi_thesaurus_ke_pgvector,
    latih_pertanyaan_sql,
    sync_global_kb_ke_pgvector,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/vanna", tags=["Admin Vanna"])


class TrainSqlRequest(BaseModel):
    branch_code: str = Field(min_length=1, max_length=50)
    question: str = Field(min_length=1, max_length=2000)
    sql: str = Field(min_length=1)


@router.post("/train")
async def admin_vanna_train(
    payload: TrainSqlRequest,
    admin: dict = Depends(require_admin_role)
):
    """Latih AI seketika: simpan contoh kueri (question -> SQL) ke pgvector."""
    core_pool = await get_core_pool()
    try:
        result = await latih_pertanyaan_sql(
            core_pool,
            branch_code=payload.branch_code,
            question=payload.question,
            sql=payload.sql,
        )
        return result
    except Exception as e:
        logger.error("Gagal melatih contoh SQL: %s", e)
        raise HTTPException(status_code=500, detail=f"Gagal melatih AI: {e}")


@router.post("/sync-global")
async def admin_vanna_sync_global(
    admin: dict = Depends(require_admin_role)
):
    """Sinkronisasi batch seluruh 2.409 kamus DDL global dan aturan thesaurus ke pgvector."""
    core_pool = await get_core_pool()
    try:
        thesaurus_count = await injeksi_thesaurus_ke_pgvector(core_pool)
        result = await sync_global_kb_ke_pgvector(core_pool, batch_size=128)
        result["thesaurus_rules_synced"] = thesaurus_count
        return result
    except Exception as e:
        logger.error("Gagal sinkronisasi global KB ke pgvector: %s", e)
        raise HTTPException(status_code=500, detail=f"Gagal sinkronisasi: {e}")


@router.post("/sync-thesaurus")
async def admin_vanna_sync_thesaurus(
    admin: dict = Depends(require_admin_role)
):
    """Sinkronisasi aturan kamus domain otomotif Indonesia ke pgvector."""
    core_pool = await get_core_pool()
    try:
        count = await injeksi_thesaurus_ke_pgvector(core_pool)
        return {"status": "success", "rules_injected": count}
    except Exception as e:
        logger.error("Gagal sinkronisasi thesaurus ke pgvector: %s", e)
        raise HTTPException(status_code=500, detail=f"Gagal sinkronisasi thesaurus: {e}")


@router.get("/items")
async def admin_vanna_items(
    branch_code: str = Query(..., min_length=1, max_length=50),
    item_type: Optional[str] = Query(None),
    admin: dict = Depends(require_admin_role)
):
    """Daftar item vektor (DDL atau contoh SQL terlatih) untuk cabang tertentu."""
    core_pool = await get_core_pool()
    conditions = ["(branch_code = $1 OR branch_code = 'GLOBAL')"]
    params = [branch_code]

    if item_type:
        conditions.append("item_type = $2")
        params.append(item_type)

    where_sql = " AND ".join(conditions)
    query = f"""
        SELECT id, branch_code, item_type, content, metadata, created_at, updated_at
        FROM tenant_vector_kb
        WHERE {where_sql}
        ORDER BY id DESC
        LIMIT 100;
    """
    rows = await core_pool.fetch(query, *params)
    return [dict(r) for r in rows]


@router.delete("/items/{item_id}")
async def admin_vanna_delete_item(
    item_id: int,
    admin: dict = Depends(require_admin_role)
):
    """Hapus item vektor dari tenant_vector_kb."""
    core_pool = await get_core_pool()
    res = await core_pool.execute("DELETE FROM tenant_vector_kb WHERE id = $1", item_id)
    if res == "DELETE 0":
        raise HTTPException(status_code=404, detail="Item vektor tidak ditemukan")
    return {"status": "deleted", "id": item_id}
