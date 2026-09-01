from cryptography.fernet import Fernet
import bcrypt
from jose import jwt
from jose.exceptions import JWTError, ExpiredSignatureError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

# Inisialisasi Fernet Cipher
fernet_cipher = Fernet(settings.fernet_key.encode())

def encrypt_credential(plain_text: str) -> str:
    return fernet_cipher.encrypt(plain_text.encode()).decode()

def decrypt_credential(encrypted_text: str) -> str:
    return fernet_cipher.decrypt(encrypted_text.encode()).decode()

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except (ValueError, TypeError):
        return False

oauth2_scheme = HTTPBearer()

async def require_admin_role(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except ExpiredSignatureError:
        # Token sudah kadaluarsa
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sudah kadaluarsa. Silakan login ulang."
        )
    except JWTError:
        # Token tidak valid atau format salah
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid. Silakan login ulang."
        )

    # Validasi user masih ada di DB dan role-nya masih admin.
    # Tanpa ini, token lama tetap berlaku 24 jam setelah user dihapus/di-demote.
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token tidak valid.")
    try:
        from app.core.database import get_core_pool
        pool = await get_core_pool()
        row = await pool.fetchrow("SELECT role, is_active FROM users WHERE id = $1", user_id)
    except Exception:
        # DB bermasalah: jangan biarkan request lewat hanya berdasarkan klaim token
        raise HTTPException(status_code=503, detail="Layanan verifikasi sedang tidak tersedia.")
    if not row or not row["is_active"] or row["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: Memerlukan role 'admin'."
        )
    return payload


async def require_user_role(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    # Guard chat (F3): kebalikan require_admin_role — admin TIDAK punya akses
    # chat (keputusan domain 2026-08-31: admin = pengatur sistem, tanpa cabang).
    # Pola sama persis: token -> cek user masih ada & aktif di DB.
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sudah kadaluarsa. Silakan login ulang."
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid. Silakan login ulang."
        )

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token tidak valid.")
    try:
        from app.core.database import get_core_pool
        pool = await get_core_pool()
        row = await pool.fetchrow("SELECT role, is_active FROM users WHERE id = $1", user_id)
    except Exception:
        # DB bermasalah: jangan biarkan request lewat hanya berdasarkan klaim token
        raise HTTPException(status_code=503, detail="Layanan verifikasi sedang tidak tersedia.")
    if not row or not row["is_active"] or row["role"] != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: fitur chat hanya untuk role 'user'."
        )
    return payload