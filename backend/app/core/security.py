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
        if payload.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak: Memerlukan role 'admin'."
            )
        return payload
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