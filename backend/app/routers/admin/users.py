from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
import asyncpg
import logging

from app.core.database import get_core_pool
from app.core.security import require_admin_role, hash_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/users", tags=["Admin - Users"])

VALID_ROLES = ("admin", "user")


# ==========================================
# SCHEMAS
# ==========================================
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr | None = None
    password: str = Field(min_length=8)
    role: str = "user"
    branch_codes: list[str] = []

class UserUpdate(BaseModel):
    email: EmailStr | None = None
    role: str | None = None
    # Password opsional saat update (kosong = tidak diubah)
    password: str | None = Field(default=None, min_length=8)
    branch_codes: list[str] | None = None

class UserStatusUpdate(BaseModel):
    is_active: bool


# ==========================================
# HELPERS
# ==========================================
async def _validate_role_and_branches(pool, role: str, branch_codes: list[str]):
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role harus salah satu dari: {', '.join(VALID_ROLES)}")
    # Keputusan domain (2026-08-31): admin = pengatur sistem (orang FBS) —
    # TIDAK punya penugasan cabang dan tidak punya akses chat AI.
    if role == "admin" and branch_codes:
        raise HTTPException(
            status_code=400,
            detail="Admin tidak memerlukan penugasan cabang — admin mengelola seluruh sistem.")
    if branch_codes:
        rows = await pool.fetch("SELECT code FROM branches WHERE code = ANY($1)", branch_codes)
        found = {r["code"] for r in rows}
        unknown = [c for c in branch_codes if c not in found]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Cabang tidak ditemukan: {', '.join(unknown)}")

async def _replace_user_branches(conn, user_id: int, branch_codes: list[str]):
    await conn.execute("DELETE FROM user_branches WHERE user_id = $1", user_id)
    for code in dict.fromkeys(branch_codes):  # dedupe, jaga urutan
        await conn.execute(
            "INSERT INTO user_branches (user_id, branches_code) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id, code
        )

async def _count_active_admins(pool) -> int:
    return int(await pool.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = TRUE"))


# ==========================================
# ENDPOINTS
# ==========================================
@router.get("")
async def get_users(user: dict = Depends(require_admin_role)):
    """Daftar semua user + cabang yang di-assign."""
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT u.id, u.username, u.email, u.role, u.is_active,
                   COALESCE(
                       ARRAY_AGG(b.code ORDER BY b.code) FILTER (WHERE b.code IS NOT NULL),
                       '{}'
                   ) AS branches
            FROM users u
            LEFT JOIN user_branches ub ON ub.user_id = u.id
            LEFT JOIN branches b ON b.code = ub.branches_code
            GROUP BY u.id
            ORDER BY u.id
        """)
        return [
            {
                "id": r["id"],
                "username": r["username"],
                "email": r["email"],
                "role": r["role"],
                "is_active": r["is_active"],
                "branches": r["branches"],
            } for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("")
async def create_user(payload: UserCreate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await _validate_role_and_branches(pool, payload.role, payload.branch_codes)

        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchval("SELECT 1 FROM users WHERE username = $1", payload.username)
                if existing:
                    raise HTTPException(status_code=400, detail="Username sudah digunakan")
                pw_hash = hash_password(payload.password)
                new_id = await conn.fetchval("""
                    INSERT INTO users (username, password_hash, email, role)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id
                """, payload.username, pw_hash, payload.email, payload.role)
                await _replace_user_branches(conn, new_id, payload.branch_codes)
        return {"message": f"User '{payload.username}' berhasil dibuat", "user_id": new_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{user_id}")
async def update_user(user_id: int, payload: UserUpdate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        target = await pool.fetchrow("SELECT id, username FROM users WHERE id = $1", user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User tidak ditemukan")

        # Validasi input yang dikirim
        new_role = payload.role
        if new_role is not None and new_role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"Role harus salah satu dari: {', '.join(VALID_ROLES)}")

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Demote admin terakhir? Tolak.
                if new_role == "user":
                    current_role = await conn.fetchval("SELECT role FROM users WHERE id = $1", user_id)
                    if current_role == "admin":
                        active_admins = await _count_active_admins(pool)
                        if active_admins <= 1:
                            raise HTTPException(status_code=400, detail="Tidak dapat mengubah role: ini satu-satunya admin aktif.")

                sets, args = [], []
                n = 0
                if payload.email is not None:
                    n += 1; sets.append(f"email = ${n}"); args.append(payload.email)
                if new_role is not None:
                    n += 1; sets.append(f"role = ${n}"); args.append(new_role)
                if payload.password:
                    n += 1; sets.append(f"password_hash = ${n}"); args.append(hash_password(payload.password))

                if sets:
                    n += 1
                    args.append(user_id)
                    await conn.execute(
                        f"UPDATE users SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ${n}",
                        *args
                    )

                if payload.branch_codes is not None:
                    if (new_role or "user") == "admin" or (new_role is None and current_role == "admin"):
                        # Safety net promote/demote: admin tidak menyimpan cabang
                        await conn.execute("DELETE FROM user_branches WHERE user_id = $1", user_id)
                    else:
                        await _validate_role_and_branches(pool, new_role or "user", payload.branch_codes)
                        await _replace_user_branches(conn, user_id, payload.branch_codes)

        return {"message": f"User '{target['username']}' berhasil diperbarui"}
    except HTTPException:
        raise
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Email sudah digunakan user lain")
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{user_id}/status")
async def set_user_status(user_id: int, payload: UserStatusUpdate, user: dict = Depends(require_admin_role)):
    """Aktifkan/nonaktifkan user (lebih aman daripada hapus permanen)."""
    try:
        pool = await get_core_pool()
        target = await pool.fetchrow("SELECT username, role, is_active FROM users WHERE id = $1", user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User tidak ditemukan")

        if not payload.is_active and target["role"] == "admin" and target["is_active"]:
            active_admins = await _count_active_admins(pool)
            if active_admins <= 1:
                raise HTTPException(status_code=400, detail="Tidak dapat menonaktifkan: ini satu-satunya admin aktif.")

        await pool.execute(
            "UPDATE users SET is_active = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
            payload.is_active, user_id
        )
        state = "diaktifkan" if payload.is_active else "dinonaktifkan"
        return {"message": f"User '{target['username']}' berhasil {state}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting status for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{user_id}")
async def delete_user(user_id: int, user: dict = Depends(require_admin_role)):
    """
    Hapus user permanen.
    Guards: bukan diri sendiri, bukan admin terakhir yang aktif.
    """
    try:
        pool = await get_core_pool()
        current_id = user.get("user_id")
        if user_id == current_id:
            raise HTTPException(status_code=400, detail="Tidak dapat menghapus akun Anda sendiri.")

        target = await pool.fetchrow("SELECT username, role, is_active FROM users WHERE id = $1", user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User tidak ditemukan")

        if target["role"] == "admin" and target["is_active"] and await _count_active_admins(pool) <= 1:
            raise HTTPException(status_code=400, detail="Tidak dapat menghapus: ini satu-satunya admin aktif.")

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM user_branches WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        return {"message": f"User '{target['username']}' berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
