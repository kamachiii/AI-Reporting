"""Endpoints admin untuk Tenant (koneksi database per cabang)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg
import logging

from app.core.database import get_core_pool
from app.core.security import require_admin_role, encrypt_credential, decrypt_credential

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Tenants"])


class TenantCreate(BaseModel):
    branch_code: str
    db_host: str
    db_port: int = 5432
    db_name: str
    db_username: str
    db_password: str


@router.get("/tenants")
async def get_tenants(user: dict = Depends(require_admin_role)):
    """
    Daftar semua tenant. Dipakai frontend via api.getTenants().
    Password TIDAK dikirim balik (hanya metadata koneksi).
    """
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT branch_code, db_host, db_port, db_name, db_username, is_active
            FROM tenants
            ORDER BY branch_code
        """)
        return [
            {
                "branch_code": r["branch_code"],
                "db_host": r["db_host"],
                "db_port": r["db_port"],
                "db_name": r["db_name"],
                "db_username": r["db_username"],
                "is_active": r["is_active"],
            } for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching tenants: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/tenants/{branch_code}")
async def get_tenant_by_branch(branch_code: str, user: dict = Depends(require_admin_role)):
    """Detail konfigurasi database satu cabang (tanpa password)."""
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow(
            "SELECT db_host, db_port, db_name, db_username FROM tenants WHERE branch_code = $1",
            branch_code
        )
        if not row:
            return None
        return {
            "db_host": row["db_host"],
            "db_port": row["db_port"],
            "db_name": row["db_name"],
            "db_username": row["db_username"]
        }
    except Exception as e:
        logger.error(f"Error fetching tenant for branch {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/tenants")
async def create_tenant(payload: TenantCreate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        # Validasi cabang benar-benar ada (hindari FK violation 500 mentah)
        branch_exists = await pool.fetchval("SELECT 1 FROM branches WHERE code = $1", payload.branch_code)
        if not branch_exists:
            raise HTTPException(status_code=404, detail=f"Cabang '{payload.branch_code}' tidak ditemukan. Buat cabang terlebih dahulu.")
        encrypted_pass = encrypt_credential(payload.db_password)
        await pool.execute("""
            INSERT INTO tenants (branch_code, db_host, db_port, db_name, db_username, db_password)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, payload.branch_code, payload.db_host, payload.db_port, payload.db_name, payload.db_username, encrypted_pass)
        return {"message": "Tenant berhasil ditambahkan"}
    except HTTPException:
        raise
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Kode cabang ini sudah memiliki konfigurasi tenant")
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise HTTPException(status_code=400, detail="Cabang tidak valid atau sudah terhapus")
    except Exception as e:
        logger.error(f"Error creating tenant: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/tenants/{branch_code}/test-connection")
async def test_tenant_connection(branch_code: str, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow("SELECT db_host, db_port, db_name, db_username, db_password FROM tenants WHERE branch_code = $1", branch_code)
        if not row:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        decrypted_pass = decrypt_credential(row["db_password"])
        conn = await asyncpg.connect(
            host=row["db_host"], port=row["db_port"], database=row["db_name"],
            user=row["db_username"], password=decrypted_pass, timeout=5.0
        )
        await conn.close()
        return {"status": "connected", "message": "Koneksi berhasil"}
    except Exception as e:
        logger.error(f"Test connection failed for {branch_code}: {e}")
        return {"status": "disconnected", "message": f"Gagal koneksi: {str(e)}"}

@router.post("/tenants/test-draft")
async def test_tenant_draft_connection(payload: TenantCreate, user: dict = Depends(require_admin_role)):
    """Menguji koneksi TANPA menyimpan (mode Create sebelum simpan)."""
    try:
        conn = await asyncpg.connect(
            host=payload.db_host,
            port=payload.db_port,
            database=payload.db_name,
            user=payload.db_username,
            password=payload.db_password,
            timeout=5.0
        )
        await conn.close()
        return {"status": "connected", "message": "Koneksi berhasil!"}
    except Exception as e:
        logger.error(f"Test draft connection failed: {e}")
        return {"status": "disconnected", "message": f"Gagal koneksi: {str(e)}"}

@router.put("/tenants/{branch_code}")
async def update_tenant(branch_code: str, payload: TenantCreate, user: dict = Depends(require_admin_role)):
    """Update konfigurasi database cabang. Password kosong = tidak diupdate."""
    try:
        pool = await get_core_pool()
        existing = await pool.fetchrow("SELECT 1 FROM tenants WHERE branch_code = $1", branch_code)
        if not existing:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")

        if payload.db_password and payload.db_password.strip():
            encrypted_pass = encrypt_credential(payload.db_password)
            await pool.execute("""
                UPDATE tenants
                SET db_host = $1, db_port = $2, db_name = $3, db_username = $4, db_password = $5
                WHERE branch_code = $6
            """, payload.db_host, payload.db_port, payload.db_name, payload.db_username, encrypted_pass, branch_code)
        else:
            await pool.execute("""
                UPDATE tenants
                SET db_host = $1, db_port = $2, db_name = $3, db_username = $4
                WHERE branch_code = $5
            """, payload.db_host, payload.db_port, payload.db_name, payload.db_username, branch_code)
        return {"message": "Tenant berhasil diperbarui"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating tenant for branch {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/tenants/{branch_code}")
async def delete_tenant(branch_code: str, user: dict = Depends(require_admin_role)):
    """Menghapus konfigurasi tenant (memutus koneksi database)."""
    try:
        pool = await get_core_pool()
        await pool.execute("DELETE FROM tenants WHERE branch_code = $1", branch_code)
        return {"message": "Tenant berhasil dihapus"}
    except Exception as e:
        logger.error(f"Error deleting tenant for branch {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
