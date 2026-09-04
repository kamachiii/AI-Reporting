"""Endpoints admin untuk KB Global — sync dari Vanna API & manajemen CRUD (F3/F3.1).

KB global menyimpan deskripsi tabel, business rules, dan contoh Q→SQL yang
berlaku lintas-tenant. Data ini di-merge dengan KB per-tenant saat pipeline
chat berjalan (muat_kb_gabungan).

Semua endpoint dilindungi require_admin_role.
"""
import json
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.database import get_core_pool
from app.core.security import require_admin_role
from app.services.vanna_sync import VannaSyncError, sync_dari_vanna

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Global KB"])


# ===========================================================================
# Model Pydantic (Validasi Ketat — field tak dikenal ditolak)
# ===========================================================================
class GlobalKBItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text", "example"] = Field(
        ..., description="Jenis item: 'text' (aturan/deskripsi) atau 'example' (Q->SQL)")
    content: str = Field(..., min_length=1, description="Isi teks atau deskripsi")
    question: str | None = Field(default=None, description="Pertanyaan untuk kind='example'")
    sql_example: str | None = Field(default=None, description="Contoh SQL untuk kind='example'")
    metadata: dict | None = Field(default=None, description="Metadata JSON opsional")


class GlobalKBItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text", "example"] | None = None
    content: str | None = Field(default=None, min_length=1)
    question: str | None = None
    sql_example: str | None = None
    metadata: dict | None = None


# ===========================================================================
# Endpoints
# ===========================================================================
@router.post("/global-kb/sync")
async def sync_global_kb(user: dict = Depends(require_admin_role)):
    """Trigger sinkronisasi KB global dari registry skema.

    Proses: fetch semua items (paginated) → upsert ke tabel
    global_knowledge_base → hapus orphan → kembalikan statistik.
    Idempoten: menjalankan berkali-kali aman.
    """
    if not settings.vanna_api_url:
        raise HTTPException(
            status_code=400,
            detail="URL registry skema belum dikonfigurasi di .env backend.")
    try:
        pool = await get_core_pool()
        stats = await sync_dari_vanna(
            pool,
            settings.vanna_api_url,
            settings.vanna_api_user,
            settings.vanna_api_password)
        return {
            "message": "Sinkronisasi kamus skema berhasil",
            "stats": stats,
        }
    except VannaSyncError as e:
        logger.error(f"Sinkronisasi kamus skema gagal: {e}")
        raise HTTPException(status_code=502,
                            detail=f"Gagal melakukan sinkronisasi kamus skema: {e}")
    except Exception as e:
        logger.error(f"Error sync KB global: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/global-kb/stats")
async def global_kb_stats(user: dict = Depends(require_admin_role)):
    """Statistik KB global (total items, per kind)."""
    try:
        pool = await get_core_pool()
        total = await pool.fetchval(
            "SELECT COUNT(*) FROM global_knowledge_base")
        text_count = await pool.fetchval(
            "SELECT COUNT(*) FROM global_knowledge_base WHERE kind = 'text'")
        example_count = await pool.fetchval(
            "SELECT COUNT(*) FROM global_knowledge_base WHERE kind = 'example'")
        return {
            "total": total or 0,
            "text": text_count or 0,
            "example": example_count or 0,
            "vanna_url": settings.vanna_api_url or "(belum dikonfigurasi)",
        }
    except Exception as e:
        logger.error(f"Error fetching global KB stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/global-kb/items")
async def list_global_kb_items(kind: str | None = None,
                               q: str | None = None,
                               limit: int = 25,
                               offset: int = 0,
                               user: dict = Depends(require_admin_role)):
    """List items KB global dengan pagination & filter opsional."""
    try:
        pool = await get_core_pool()
        conditions = []
        params = []
        param_idx = 1

        if kind:
            conditions.append(f"kind = ${param_idx}")
            params.append(kind)
            param_idx += 1
        if q:
            conditions.append(f"(content ILIKE ${param_idx} OR question ILIKE ${param_idx})")
            params.append(f"%{q}%")
            param_idx += 1

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        # Count query
        count_sql = f"SELECT COUNT(*) FROM global_knowledge_base {where}"
        total = await pool.fetchval(count_sql, *params)

        # Data query
        data_sql = (
            f"SELECT id, external_id, kind, content, question, sql_example, "
            f"created_at, updated_at "
            f"FROM global_knowledge_base {where} "
            f"ORDER BY updated_at DESC "
            f"LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        )
        params.extend([limit, offset])
        rows = await pool.fetch(data_sql, *params)

        return {
            "total": total or 0,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": r["id"],
                    "external_id": r["external_id"],
                    "kind": r["kind"],
                    "content": r["content"],
                    "question": r["question"],
                    "sql_example": r["sql_example"],
                    "created_at": r["created_at"].isoformat()
                    if r["created_at"] else None,
                    "updated_at": r["updated_at"].isoformat()
                    if r["updated_at"] else None,
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.error(f"Error listing global KB items: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/global-kb/items", status_code=201)
async def create_global_kb_item(payload: GlobalKBItemCreate,
                                user: dict = Depends(require_admin_role)):
    """Buat item KB global baru secara manual."""
    try:
        pool = await get_core_pool()
        external_id = f"manual_{uuid.uuid4().hex[:12]}"
        meta_json = json.dumps(payload.metadata, ensure_ascii=False) if payload.metadata else None

        row = await pool.fetchrow(
            "INSERT INTO global_knowledge_base "
            "(external_id, kind, content, question, sql_example, metadata, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "RETURNING id, external_id, kind, content, question, sql_example, metadata, created_at, updated_at",
            external_id, payload.kind, payload.content, payload.question,
            payload.sql_example, meta_json
        )
        return {
            "message": "Item KB global berhasil dibuat",
            "item": {
                "id": row["id"],
                "external_id": row["external_id"],
                "kind": row["kind"],
                "content": row["content"],
                "question": row["question"],
                "sql_example": row["sql_example"],
                "metadata": payload.metadata,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
        }
    except Exception as e:
        logger.error(f"Error creating global KB item: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/global-kb/items/{item_id}")
async def get_global_kb_item(item_id: int,
                             user: dict = Depends(require_admin_role)):
    """Ambil detail satu item KB global berdasarkan ID."""
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow(
            "SELECT id, external_id, kind, content, question, sql_example, metadata, created_at, updated_at "
            "FROM global_knowledge_base WHERE id = $1",
            item_id
        )
        if not row:
            raise HTTPException(status_code=404,
                                detail=f"Item KB global #{item_id} tidak ditemukan.")
        meta = row["metadata"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                pass
        return {
            "id": row["id"],
            "external_id": row["external_id"],
            "kind": row["kind"],
            "content": row["content"],
            "question": row["question"],
            "sql_example": row["sql_example"],
            "metadata": meta,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting global KB item #{item_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/global-kb/items/{item_id}")
async def update_global_kb_item(item_id: int,
                                payload: GlobalKBItemUpdate,
                                user: dict = Depends(require_admin_role)):
    """Update item KB global existing."""
    try:
        pool = await get_core_pool()
        existing = await pool.fetchrow(
            "SELECT id, external_id, kind, content, question, sql_example, metadata "
            "FROM global_knowledge_base WHERE id = $1",
            item_id
        )
        if not existing:
            raise HTTPException(status_code=404,
                                detail=f"Item KB global #{item_id} tidak ditemukan.")

        new_kind = payload.kind if payload.kind is not None else existing["kind"]
        new_content = payload.content if payload.content is not None else existing["content"]
        new_question = payload.question if payload.question is not None else existing["question"]
        new_sql = payload.sql_example if payload.sql_example is not None else existing["sql_example"]
        new_meta = json.dumps(payload.metadata, ensure_ascii=False) if payload.metadata is not None else (
            existing["metadata"] if isinstance(existing["metadata"], str) else (
                json.dumps(existing["metadata"]) if existing["metadata"] else None
            )
        )

        row = await pool.fetchrow(
            "UPDATE global_knowledge_base "
            "SET kind = $1, content = $2, question = $3, sql_example = $4, metadata = $5, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = $6 "
            "RETURNING id, external_id, kind, content, question, sql_example, metadata, created_at, updated_at",
            new_kind, new_content, new_question, new_sql, new_meta, item_id
        )
        return {
            "message": f"Item KB global #{item_id} berhasil diperbarui",
            "item": {
                "id": row["id"],
                "external_id": row["external_id"],
                "kind": row["kind"],
                "content": row["content"],
                "question": row["question"],
                "sql_example": row["sql_example"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating global KB item #{item_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/global-kb/items/{item_id}")
async def delete_global_kb_item(item_id: int,
                                user: dict = Depends(require_admin_role)):
    """Hapus item KB global berdasarkan ID."""
    try:
        pool = await get_core_pool()
        result = await pool.execute(
            "DELETE FROM global_knowledge_base WHERE id = $1", item_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404,
                                detail=f"Item KB global #{item_id} tidak ditemukan.")
        return {"message": f"Item KB global #{item_id} berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting global KB item {item_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
