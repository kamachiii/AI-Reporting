"""Endpoints admin untuk Tenant (penunjuk cabang -> database).

Model baru: tenants TIDAK menyimpan kredensial. Satu baris tenant
= penunjuk satu cabang ke satu entri di db_connections.
Satu cabang = satu database; satu database boleh dipakai banyak cabang.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg
import logging

from app.core.database import get_core_pool
from app.core.security import require_admin_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Tenants"])


class TenantCreate(BaseModel):
    branch_code: str
    db_connection_id: int


@router.get("/tenants")
async def get_tenants(user: dict = Depends(require_admin_role)):
    """
    Daftar semua tenant (cabang yang terhubung database).
    Kredensial tidak dikirim balik — hanya metadata ringkas.
    """
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT t.branch_code, t.db_connection_id,
                   dc.name AS db_name_label, dc.db_host, dc.db_port,
                   dc.db_name, t.is_active
            FROM tenants t
            JOIN db_connections dc ON dc.id = t.db_connection_id
            ORDER BY t.branch_code
        """)
        return [
            {
                "branch_code": r["branch_code"],
                "db_connection_id": r["db_connection_id"],
                "db_name_label": r["db_name_label"],
                "db_host": r["db_host"],
                "db_port": r["db_port"],
                "db_name": r["db_name"],
                "is_active": r["is_active"],
            } for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching tenants: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/tenants")
async def create_tenant(payload: TenantCreate, user: dict = Depends(require_admin_role)):
    """Hubungkan cabang ke database registry (pilih dari dropdown)."""
    try:
        pool = await get_core_pool()
        branch_exists = await pool.fetchval("SELECT 1 FROM branches WHERE code = $1", payload.branch_code)
        if not branch_exists:
            raise HTTPException(status_code=404,
                detail=f"Cabang '{payload.branch_code}' tidak ditemukan.")
        conn_row = await pool.fetchrow(
            "SELECT id, is_active FROM db_connections WHERE id = $1", payload.db_connection_id)
        if not conn_row:
            raise HTTPException(status_code=404,
                detail=f"Database dengan ID {payload.db_connection_id} tidak ada di registry.")
        if not conn_row["is_active"]:
            raise HTTPException(status_code=400,
                detail="Database ini sedang dinonaktifkan di registry dan tidak bisa dihubungkan.")

        # Satu cabang hanya boleh satu database (UNIQUE branch_code juga menjaga)
        already = await pool.fetchval("SELECT 1 FROM tenants WHERE branch_code = $1", payload.branch_code)
        if already:
            raise HTTPException(status_code=400,
                detail=f"Cabang {payload.branch_code} sudah terhubung ke sebuah database. Putuskan dulu jika ingin mengganti.")

        await pool.execute("""
            INSERT INTO tenants (branch_code, db_connection_id)
            VALUES ($1, $2)
        """, payload.branch_code, payload.db_connection_id)
        return {"message": f"Database berhasil dihubungkan ke cabang {payload.branch_code}"}
    except HTTPException:
        raise
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Cabang ini sudah memiliki database")
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise HTTPException(status_code=400, detail="Cabang atau database tidak valid")
    except Exception as e:
        logger.error(f"Error creating tenant: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/tenants/{branch_code}")
async def update_tenant(branch_code: str, payload: TenantCreate, user: dict = Depends(require_admin_role)):
    """Ganti database yang ditunjuk cabang."""
    try:
        pool = await get_core_pool()
        existing = await pool.fetchrow(
            "SELECT db_connection_id FROM tenants WHERE branch_code = $1", branch_code)
        if not existing:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")

        new_conn = payload.db_connection_id
        if new_conn != existing["db_connection_id"]:
            conn_ok = await pool.fetchval(
                "SELECT is_active FROM db_connections WHERE id = $1", new_conn)
            if conn_ok is None:
                raise HTTPException(status_code=404,
                    detail=f"Database dengan ID {new_conn} tidak ada di registry.")
            if not conn_ok:
                raise HTTPException(status_code=400,
                    detail="Database tujuan sedang dinonaktifkan di registry.")

            await pool.execute("""
                UPDATE tenants SET db_connection_id = $1, updated_at = CURRENT_TIMESTAMP
                WHERE branch_code = $2
            """, new_conn, branch_code)
        return {"message": f"Database cabang {branch_code} berhasil diganti"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating tenant {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/tenants/{branch_code}")
async def delete_tenant(branch_code: str, user: dict = Depends(require_admin_role)):
    """Putuskan koneksi database dari cabang (tenant dihapus; registry tetap)."""
    try:
        pool = await get_core_pool()
        result = await pool.execute("DELETE FROM tenants WHERE branch_code = $1", branch_code)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        return {"message": f"Koneksi database cabang {branch_code} berhasil diputus"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting tenant {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/tenants/{branch_code}/test-connection")
async def test_tenant_connection(branch_code: str, user: dict = Depends(require_admin_role)):
    """Tes koneksi nyata database milik cabang (via registry)."""
    from app.core.security import decrypt_credential
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow("""
            SELECT dc.id, dc.db_host, dc.db_port, dc.db_name, dc.db_username, dc.db_password
            FROM tenants t
            JOIN db_connections dc ON dc.id = t.db_connection_id
            WHERE t.branch_code = $1
        """, branch_code)
        if not row:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        password = decrypt_credential(row["db_password"])
        conn = await asyncpg.connect(
            host=row["db_host"], port=row["db_port"], database=row["db_name"],
            user=row["db_username"], password=password, timeout=5.0)
        await conn.close()
        return {"status": "connected", "message": "Koneksi berhasil"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test connection failed for {branch_code}: {e}")
        return {"status": "disconnected", "message": f"Gagal koneksi: {str(e)}"}
