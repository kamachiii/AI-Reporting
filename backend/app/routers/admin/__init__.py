"""Admin router package: satu modul per domain.

main.py cukup melakukan:
    from app.routers import admin
    app.include_router(admin.router)

router gabungan ini menyatukan semua sub-router per domain.
"""
from fastapi import APIRouter

from app.routers.admin.companies import router as companies_router
from app.routers.admin.users import router as users_router
from app.routers.admin.db_connections import router as db_connections_router
from app.routers.admin.db_status import router as db_status_router
from app.routers.admin.tenants import router as tenants_router
from app.routers.admin.ai_configs import router as ai_configs_router
from app.routers.admin.audit_logs import router as audit_logs_router

router = APIRouter()
router.include_router(companies_router)
router.include_router(users_router)
router.include_router(db_connections_router)
router.include_router(db_status_router)
router.include_router(tenants_router)
router.include_router(ai_configs_router)
router.include_router(audit_logs_router)
