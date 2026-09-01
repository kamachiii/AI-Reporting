from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.database import get_core_pool, close_core_pool, get_redis
from app.routers import auth, admin, chat
from app.services.tenant_pool import get_tenant_pool_manager

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logging.info("Starting up...")
    await get_core_pool()
    try:
        await get_redis()
    except Exception as e:
        # Redis belum dipakai fitur manapun (disiapkan untuk cache/rate-limit Fase 6):
        # jangan gagalkan startup hanya karena Redis mati.
        logging.warning(f"Redis tidak tersedia, startup lanjut tanpa Redis: {e}")
    yield
    # Shutdown
    await get_tenant_pool_manager().close_all()  # F2.4: pool tenant LRU
    await close_core_pool()
    logging.info("Shutdown complete.")

app = FastAPI(title="DMS AI Platform API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(chat.router)

@app.get("/")
async def root():
    return {"message": "DMS AI Platform Backend is running!"}