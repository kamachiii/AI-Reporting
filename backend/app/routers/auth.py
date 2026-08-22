from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta
import logging
from app.core.config import settings
from app.core.database import get_core_pool
from app.core.security import verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    allowed_branches: list[str]

@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    try:
        pool = await get_core_pool()
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise HTTPException(status_code=500, detail="Database connection error")

    user = await pool.fetchrow(
        "SELECT id, username, password_hash, role FROM users WHERE username = $1",
        req.username
    )
    if not user:
        raise HTTPException(status_code=401, detail="Username atau password salah")

    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Username atau password salah")

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
        "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    return LoginResponse(
        access_token=token,
        user_id=user["id"],
        role=user["role"],
        allowed_branches=allowed_branches
    )