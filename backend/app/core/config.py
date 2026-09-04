import os
import sys
import logging
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Database Core
    core_db_host: str = os.getenv("CORE_DB_HOST", "localhost")
    core_db_port: int = int(os.getenv("CORE_DB_PORT", "5433"))
    core_db_name: str = os.getenv("CORE_DB_NAME", "ai-dms")
    core_db_user: str = os.getenv("CORE_DB_USER", "postgres")
    core_db_password: str = os.getenv("CORE_DB_PASSWORD", "postgres")

    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # JWT
    secret_key: str = os.getenv("JWT_SECRET_KEY", "")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # Fernet (enkripsi password DB tenant & API Key AI)
    fernet_key: str = os.getenv("FERNET_KEY", "")

    # CORS (asal tambahan selain localhost/127.0.0.1, pisahkan dengan koma)
    cors_origins: str = os.getenv("CORS_ORIGINS", "")

    # Eksekusi Query Tenant (Gerbang #6)
    statement_timeout: str = os.getenv("STATEMENT_TIMEOUT", "10s")
    query_row_cap: int = int(os.getenv("QUERY_ROW_CAP", "500"))

    # Rate Limiting Chat User
    chat_rate_limit_max: int = int(os.getenv("CHAT_RATE_LIMIT_MAX", "10"))
    chat_rate_limit_window: int = int(os.getenv("CHAT_RATE_LIMIT_WINDOW", "60"))

    # Timeout Provider AI (detik)
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "60.0"))

    # Tenant Pool Manager (LRU Cache Pool DB Tenant)
    tenant_max_pools: int = int(os.getenv("TENANT_MAX_POOLS", "8"))
    tenant_pool_max_size: int = int(os.getenv("TENANT_POOL_MAX_SIZE", "2"))
    tenant_idle_timeout_seconds: float = float(os.getenv("TENANT_IDLE_TIMEOUT_SECONDS", "600.0"))

    # Vanna API (sumber KB global — opsional, sync gagal = KB global kosong)
    vanna_api_url: str = os.getenv("VANNA_API_URL", "")
    vanna_api_user: str = os.getenv("VANNA_API_USER", "")
    vanna_api_password: str = os.getenv("VANNA_API_PASSWORD", "")

    # Few-shot examples (jumlah contoh yang diinjeksi ke prompt LLM)
    fewshot_max_examples: int = int(os.getenv("FEWSHOT_MAX_EXAMPLES", "5"))


settings = Settings()

# --- Validasi startup (fail-fast) ---
# Tanpa ini, JWT bisa dipalsukan dengan secret default dan Fernet crash saat import.
_errors = []
if not settings.secret_key or settings.secret_key == "super_secret_key_change_me":
    _errors.append(
        "JWT_SECRET_KEY belum diisi (atau masih memakai nilai placeholder). "
        "Isi minimal 32 karakter acak di backend/.env"
    )
if len(settings.secret_key or "") < 32 and settings.secret_key != "super_secret_key_change_me" and settings.secret_key:
    _errors.append("JWT_SECRET_KEY terlalu pendek (minimal 32 karakter).")
if not settings.fernet_key:
    _errors.append(
        "FERNET_KEY belum diisi. Generate dengan: "
        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

if _errors:
    for err in _errors:
        logger.critical(f"FATAL CONFIG: {err}")
    print("=" * 60)
    print("FATAL: Konfigurasi backend tidak valid:")
    for err in _errors:
        print(f"  - {err}")
    print("=" * 60)
    sys.exit(1)

# Validasi FERNET_KEY benar-benar usable (bukan string random)
try:
    from cryptography.fernet import Fernet
    Fernet(settings.fernet_key.encode())
except Exception as e:
    print(f"FATAL: FERNET_KEY tidak valid: {e}")
    sys.exit(1)