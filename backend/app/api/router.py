"""API router assembly."""

from fastapi import APIRouter

from app.api.v1 import health, logs, machines, models

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(logs.router)
api_router.include_router(models.router)
api_router.include_router(machines.router)
