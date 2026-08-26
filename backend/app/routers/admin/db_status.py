"""Endpoint batch untuk tes koneksi seluruh registry database sekaligus.

Alasan: status koneksi adalah properti DATABASE (bukan relasi cabang),
jadi cukup 1 request untuk mengetes semuanya secara paralel — ringan
bagi browser maupun backend.
"""
import asyncio

from fastapi import APIRouter, Depends
import asyncpg
import logging

from app.core.database import get_core_pool
from app.core.security import require_admin_role, decrypt_credential

logger = logging.getLogger(__name__)

# dipakai bersama dengan router utama admin
router = APIRouter(prefix="/admin", tags=["Admin - Database Registry"])


async def _probe(row) -> tuple[int, dict]:
    """Tes satu koneksi; tidak pernah raise — selalu return hasil."""
    try:
        password = decrypt_credential(row["db_password"])
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=row["db_host"], port=row["db_port"], database=row["db_name"],
                user=row["db_username"], password=password,
            ),
            timeout=4.0,
        )
        await conn.close()
        return row["id"], {"status": "connected", "message": "Koneksi berhasil"}
    except asyncio.TimeoutError:
        return row["id"], {"status": "disconnected", "message": f"Timeout: {row['db_host']}:{row['db_port']}"}
    except Exception as e:
        msg = str(e).split("\n")[0][:120]
        return row["id"], {"status": "disconnected", "message": msg}


@router.post("/db-connections/test-all")
async def test_all_db_connections(user: dict = Depends(require_admin_role)):
    """
    Tes koneksi SEMUA database terdaftar secara paralel.
    Return: { "<conn_id>": {status, message}, ... }
    """
    try:
        pool = await get_core_pool()
        rows = await pool.fetch(
            "SELECT id, db_host, db_port, db_name, db_username, db_password FROM db_connections"
        )
        if not rows:
            return {}

        results = await asyncio.gather(*(_probe(r) for r in rows))
        return {str(cid): payload for cid, payload in results}
    except Exception as e:
        logger.error(f"test-all failed: {e}")
        # tetap balikkan struktur agar frontend bisa render 'disconnected'
        return {}
