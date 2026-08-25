"""Endpoints admin untuk Company & Branch."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg
import logging

from app.core.database import get_core_pool
from app.core.security import require_admin_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Companies & Branches"])


class CompanyCreate(BaseModel):
    code: str
    name: str
    address: str = ""

class CompanyUpdate(BaseModel):
    name: str
    address: str = ""
    is_active: bool = True

class BranchCreate(BaseModel):
    code: str
    name: str
    company_code: str
    address: str = ""

class BranchUpdate(BaseModel):
    name: str
    address: str = ""
    is_active: bool = True


@router.get("/companies")
async def get_companies(user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("SELECT code, name, address, is_active FROM companies")
        return [{"code": r["code"], "name": r["name"], "address": r["address"], "is_active": r["is_active"]} for r in rows]
    except Exception as e:
        logger.error(f"Error fetching companies: {e}")
        return []

@router.post("/companies")
async def create_company(payload: CompanyCreate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await pool.execute("INSERT INTO companies (code, name, address) VALUES ($1, $2, $3)", payload.code, payload.name, payload.address)
        return {"message": "Perusahaan berhasil ditambahkan"}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Kode perusahaan sudah digunakan")
    except Exception as e:
        logger.error(f"Error creating company: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/companies/{code}")
async def update_company(code: str, payload: CompanyUpdate, user: dict = Depends(require_admin_role)):
    """
    Update perusahaan (transaksional).
    - Nonaktifkan  -> semua cabang ikut nonaktif.
    - Aktifkan     -> cabang diaktifkan kembali (simetris).
    """
    try:
        pool = await get_core_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval("SELECT 1 FROM companies WHERE code=$1", code)
                if not exists:
                    raise HTTPException(status_code=404, detail="Perusahaan tidak ditemukan")
                await conn.execute(
                    "UPDATE companies SET name=$1, address=$2, is_active=$3 WHERE code=$4",
                    payload.name, payload.address, payload.is_active, code
                )
                if not payload.is_active:
                    await conn.execute("UPDATE branches SET is_active=false WHERE company_code=$1", code)
                else:
                    await conn.execute("UPDATE branches SET is_active=true WHERE company_code=$1", code)
        return {"message": "Perusahaan berhasil diperbarui"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating company: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/companies/{code}")
async def delete_company(code: str, user: dict = Depends(require_admin_role)):
    """
    Hapus perusahaan + seluruh cabangnya secara transaksional.
    Menolak jika masih ada tenant terpasang pada cabang manapun.
    """
    try:
        pool = await get_core_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval("SELECT 1 FROM companies WHERE code=$1", code)
                if not exists:
                    raise HTTPException(status_code=404, detail="Perusahaan tidak ditemukan")
                tenant_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM tenants t
                    JOIN branches b ON t.branch_code = b.code
                    WHERE b.company_code = $1
                """, code)
                if tenant_count and int(tenant_count) > 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Tidak dapat menghapus: {tenant_count} konfigurasi database (tenant) masih terhubung. Hapus tenant pada menu Database & Tenant terlebih dahulu."
                    )
                await conn.execute("""
                    DELETE FROM user_branches WHERE branches_code IN (
                        SELECT code FROM branches WHERE company_code = $1
                    )
                """, code)
                await conn.execute("DELETE FROM branches WHERE company_code = $1", code)
                await conn.execute("DELETE FROM companies WHERE code = $1", code)
        return {"message": "Perusahaan berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting company: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/branches")
async def get_branches(user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("SELECT b.code, b.name, b.company_code, b.address, b.is_active FROM branches b")
        return [{"code": r["code"], "name": r["name"], "company_code": r["company_code"], "address": r["address"], "is_active": r["is_active"]} for r in rows]
    except Exception as e:
        logger.error(f"Error fetching branches: {e}")
        return []

@router.post("/branches")
async def create_branch(payload: BranchCreate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await pool.execute("INSERT INTO branches (code, name, company_code, address) VALUES ($1, $2, $3, $4)", payload.code, payload.name, payload.company_code, payload.address)
        return {"message": "Cabang berhasil ditambahkan"}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Kode cabang sudah digunakan")
    except Exception as e:
        logger.error(f"Error creating branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/branches/{code}")
async def update_branch(code: str, payload: BranchUpdate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await pool.execute("UPDATE branches SET name=$1, address=$2, is_active=$3 WHERE code=$4", payload.name, payload.address, payload.is_active, code)
        return {"message": "Cabang berhasil diperbarui"}
    except Exception as e:
        logger.error(f"Error updating branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/branches/{code}")
async def delete_branch(code: str, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        tenant_exists = await pool.fetchval("SELECT 1 FROM tenants WHERE branch_code = $1", code)
        if tenant_exists:
            raise HTTPException(
                status_code=400,
                detail="Tidak dapat menghapus: cabang ini masih memiliki konfigurasi database (tenant). Hapus tenant terlebih dahulu."
            )
        await pool.execute("DELETE FROM branches WHERE code=$1", code)
        return {"message": "Cabang berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/branches-with-tenants")
async def get_branches_with_tenants(user: dict = Depends(require_admin_role)):
    """Branch + metadata tenant (tanpa password) untuk tabel integrasi."""
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT
                b.code, b.name, b.company_code, b.address, b.is_active,
                t.db_host, t.db_port, t.db_name, t.db_username
            FROM branches b
            LEFT JOIN tenants t ON b.code = t.branch_code
        """)
        return [{"code": r["code"], "name": r["name"], "company_code": r["company_code"], "address": r["address"], "is_active": r["is_active"], "db_host": r["db_host"], "db_port": r["db_port"], "db_name": r["db_name"], "db_username": r["db_username"]} for r in rows]
    except Exception as e:
        logger.error(f"Error fetching branches with tenants: {e}")
        return []
