"""Endpoints admin untuk Registry Database (db_connections).

Model: kredensial database didaftarkan sekali di sini; cabang
(tenants) hanya menunjuk ke salah satu entri registry.
Satu cabang = satu database; satu database boleh dipakai banyak cabang.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg
import logging

from app.core.database import get_core_pool
from app.core.security import require_admin_role, encrypt_credential

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Database Registry"])


class DbConnectionCreate(BaseModel):
    name: str
    db_host: str
    db_port: int = 5432
    db_name: str
    db_username: str
    db_password: str


@router.get("/db-connections")
async def get_db_connections(user: dict = Depends(require_admin_role)):
    """Daftar semua database terdaftar (tanpa password)."""
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT dc.id, dc.name, dc.db_host, dc.db_port, dc.db_name,
                   dc.db_username, dc.is_active,
                   COUNT(t.branch_code) AS used_by
            FROM db_connections dc
            LEFT JOIN tenants t ON t.db_connection_id = dc.id
            GROUP BY dc.id
            ORDER BY dc.name
        """)
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "db_host": r["db_host"],
                "db_port": r["db_port"],
                "db_name": r["db_name"],
                "db_username": r["db_username"],
                "is_active": r["is_active"],
                "used_by": int(r["used_by"]),
            } for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching db connections: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/db-connections")
async def create_db_connection(payload: DbConnectionCreate, user: dict = Depends(require_admin_role)):
    """Daftarkan database baru ke registry (password dienkripsi Fernet)."""
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nama database wajib diisi")
    try:
        pool = await get_core_pool()
        encrypted = encrypt_credential(payload.db_password)
        new_id = await pool.fetchval("""
            INSERT INTO db_connections (name, db_host, db_port, db_name, db_username, db_password)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, payload.name.strip(), payload.db_host, payload.db_port,
            payload.db_name, payload.db_username, encrypted)
        return {"message": f"Database '{payload.name}' berhasil didaftarkan", "id": new_id}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail=f"Nama database '{payload.name}' sudah digunakan")
    except Exception as e:
        logger.error(f"Error creating db connection: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/db-connections/{conn_id}")
async def update_db_connection(conn_id: int, payload: DbConnectionCreate, user: dict = Depends(require_admin_role)):
    """Update entri registry. Password kosong = tidak diubah."""
    try:
        pool = await get_core_pool()
        existing = await pool.fetchrow("SELECT id FROM db_connections WHERE id = $1", conn_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Database tidak ditemukan")
        if payload.db_password and payload.db_password.strip():
            encrypted = encrypt_credential(payload.db_password)
            await pool.execute("""
                UPDATE db_connections
                SET name=$1, db_host=$2, db_port=$3, db_name=$4, db_username=$5, db_password=$6
                WHERE id=$7
            """, payload.name.strip(), payload.db_host, payload.db_port,
                payload.db_name, payload.db_username, encrypted, conn_id)
        else:
            await pool.execute("""
                UPDATE db_connections
                SET name=$1, db_host=$2, db_port=$3, db_name=$4, db_username=$5
                WHERE id=$6
            """, payload.name.strip(), payload.db_host, payload.db_port,
                payload.db_name, payload.db_username, conn_id)
        return {"message": "Database berhasil diperbarui"}
    except HTTPException:
        raise
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail=f"Nama database '{payload.name}' sudah digunakan")
    except Exception as e:
        logger.error(f"Error updating db connection {conn_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/db-connections/{conn_id}")
async def delete_db_connection(conn_id: int, user: dict = Depends(require_admin_role)):
    """Hapus entri registry. Ditolak jika masih ada cabang yang memakainya."""
    try:
        pool = await get_core_pool()
        used = await pool.fetchval("SELECT COUNT(*) FROM tenants WHERE db_connection_id = $1", conn_id)
        if used and int(used) > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Tidak dapat menghapus: {used} cabang masih menggunakan database ini. Putuskan dulu dari cabang tersebut."
            )
        result = await pool.execute("DELETE FROM db_connections WHERE id = $1", conn_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Database tidak ditemukan")
        return {"message": "Database berhasil dihapus dari registry"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting db connection {conn_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/db-connections/{conn_id}/test-connection")
async def test_db_connection(conn_id: int, user: dict = Depends(require_admin_role)):
    """Tes koneksi nyata ke database yang terdaftar (dekripsi password)."""
    from app.core.security import decrypt_credential
    import asyncpg as _asyncpg
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow(
            "SELECT db_host, db_port, db_name, db_username, db_password FROM db_connections WHERE id = $1",
            conn_id)
        if not row:
            raise HTTPException(status_code=404, detail="Database tidak ditemukan")
        password = decrypt_credential(row["db_password"])
        conn = await _asyncpg.connect(
            host=row["db_host"], port=row["db_port"], database=row["db_name"],
            user=row["db_username"], password=password, timeout=5.0)
        await conn.close()
        return {"status": "connected", "message": "Koneksi berhasil"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test connection failed for db_connection {conn_id}: {e}")
        return {"status": "disconnected", "message": f"Gagal koneksi: {str(e)}"}
