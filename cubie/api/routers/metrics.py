from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from cubie.api.routers.auth import build_require_scoped_api_key
from cubie.auth.api_key_store import METRICS_SCOPE
from cubie.core.observability.metrics import render_metrics

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_metrics_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_metrics_token = build_require_scoped_api_key(container, METRICS_SCOPE)

    @router.get(
        "/metrics",
        response_class=PlainTextResponse,
        dependencies=[Depends(require_metrics_token)],
    )
    async def metrics() -> str:
        return render_metrics(ready=container.engine.ready)

    return router
