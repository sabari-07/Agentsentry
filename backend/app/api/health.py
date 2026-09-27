"""Health/metadata endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core import Container, get_container

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(container: Container = Depends(get_container)) -> dict:
    return {
        "status": "ok",
        "mode": "mock" if container.settings.use_mock_data else "live",
        "region": container.settings.region,
    }
