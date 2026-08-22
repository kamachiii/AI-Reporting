import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Database Core
    core_db_host: str = os.getenv("CORE_DB_HOST", "localhost")
    core_db_port: int = int(os.getenv("CORE_DB_PORT", "5433"))
    core_db_name: str = os.getenv("CORE_DB_NAME", "platform_core")
    core_db_user: str = os.getenv("CORE_DB_USER", "postgres")
    core_db_password: str = os.getenv("CORE_DB_PASSWORD", "postgres")
    
    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # JWT
    secret_key: str = os.getenv("JWT_SECRET_KEY", "super_secret_key_change_me")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 jam
    
    # Fernet (enkripsi password DB tenant & API Key AI)
    fernet_key: str = os.getenv("FERNET_KEY", "")

settings = Settings()