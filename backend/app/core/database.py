import asyncpg
import redis.asyncio as redis
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Global variable untuk pool
core_pool = None
redis_client = None

async def get_core_pool():
    global core_pool
    if core_pool is None:
        dsn = f"postgresql://{settings.core_db_user}:{settings.core_db_password}@{settings.core_db_host}:{settings.core_db_port}/{settings.core_db_name}"
        try:
            core_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
            logger.info("Core database pool created.")
        except Exception as e:
            logger.error(f"Failed to create core database pool: {e}")
            raise
    return core_pool

async def close_core_pool():
    global core_pool
    if core_pool:
        await core_pool.close()
        core_pool = None
        logger.info("Core database pool closed.")

async def get_redis():
    global redis_client
    if redis_client is None:
        try:
            redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            await redis_client.ping()
            logger.info("Redis connected.")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    return redis_client