from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from cubie.api.schemas import HealthResponse

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_health_router(container: AppContainer) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service=container.config.service_name)

    @router.get("/readiness", response_model=HealthResponse)
    async def readiness() -> HealthResponse:
        if container.engine.ready:
            return HealthResponse(status="ready", service=container.config.service_name)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=HealthResponse(
                status="not_ready",
                service=container.config.service_name,
            ).model_dump(),
        )

    @router.get("/ready", response_model=HealthResponse, include_in_schema=False)
    async def ready() -> HealthResponse:
        return await readiness()

    return router
