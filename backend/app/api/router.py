"""API router assembly."""

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    analytics,
    audit,
    auth,
    cases,
    dashboard,
    health,
    logs,
    machines,
    models,
    transactions,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(logs.router)
api_router.include_router(models.router)
api_router.include_router(machines.router)
api_router.include_router(transactions.router)
api_router.include_router(dashboard.router)
api_router.include_router(ai.router)
api_router.include_router(analytics.router)
api_router.include_router(cases.router)
api_router.include_router(audit.router)
