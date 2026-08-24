from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.database import get_core_pool, close_core_pool, get_redis
from app.routers import auth, admin, users

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logging.info("Starting up...")
    await get_core_pool()
    await get_redis()
    yield
    # Shutdown
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
app.include_router(users.router)

@app.get("/")
async def root():
    return {"message": "DMS AI Platform Backend is running!"}