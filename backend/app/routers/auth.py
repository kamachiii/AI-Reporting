from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
import time
import logging
from app.core.config import settings
from app.core.database import get_core_pool
from app.core.security import verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

# --- Rate limiting sederhana (anti brute-force) ---
# Maksimal 5 percobaan GAGAL per kombinasi username+IP dalam 60 detik.
# Sukses login menghapus hitungan. In-memory: cukup untuk single-instance dev/PKL.
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 60
_login_attempts: dict[str, deque] = defaultdict(deque)


class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: str
    allowed_branches: list[str]

@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request):
    # --- Cek rate limit sebelum sentuh database ---
    client_ip = request.client.host if request.client else "unknown"
    attempt_key = f"{req.username.lower()}:{client_ip}"
    attempts = _login_attempts[attempt_key]
    now = time.monotonic()
    while attempts and now - attempts[0] > _LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        logger.warning(f"Rate limit triggered for {attempt_key}")
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak percobaan login. Coba lagi dalam {_LOGIN_WINDOW_SECONDS} detik."
        )

    try:
        pool = await get_core_pool()
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise HTTPException(status_code=500, detail="Database connection error")

    user = await pool.fetchrow(
        "SELECT id, username, password_hash, role, is_active FROM users WHERE username = $1",
        req.username
    )
    if not user:
        attempts.append(now)
        raise HTTPException(status_code=401, detail="Username atau password salah")

    if not user["is_active"]:
        # Akun dinonaktifkan admin — pesan spesifik agar tidak membingungkan
        attempts.append(now)
        raise HTTPException(status_code=403, detail="Akun Anda dinonaktifkan. Hubungi administrator.")

    if not verify_password(req.password, user["password_hash"]):
        attempts.append(now)
        raise HTTPException(status_code=401, detail="Username atau password salah")

    # Login sukses -> reset hitungan gagal untuk user ini
    attempts.clear()

    try:
        rows = await pool.fetch("""
            SELECT b.code FROM user_branches ub
            JOIN branches b ON ub.branches_code = b.code
            WHERE ub.user_id = $1 AND b.is_active = true
        """, user["id"])
        allowed_branches = [row["code"] for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch allowed branches: {e}")
        allowed_branches = []

    payload = {
        "sub": str(user["id"]),
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "allowed_branches": allowed_branches,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    return LoginResponse(
        access_token=token,
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        allowed_branches=allowed_branches
    )
