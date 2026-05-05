from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query, status

from cubie.api.helpers.auth import build_require_admin_token

from .create import handle_create_model
from .handlers import (
    handle_delete_model,
    handle_get_model,
    handle_get_model_deps,
    handle_list_models,
    handle_list_provider_deps,
    handle_load_model,
    handle_unload_model,
    handle_update_model,
)

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_admin_models_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.get(
        "/api/admin/models",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_models(include_pending: bool = Query(default=False)) -> dict:
        return await handle_list_models(
            container,
            include_pending=include_pending,
        )

    @router.get(
        "/api/admin/providers/{provider_type}/deps",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_provider_deps(provider_type: str) -> list[dict]:
        return await handle_list_provider_deps(
            container,
            provider_type=provider_type,
        )

    @router.get(
        "/api/admin/models/{model_id}/deps",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_model_deps(model_id: str) -> list[dict]:
        return await handle_get_model_deps(
            container,
            model_id=model_id,
        )

    @router.post(
        "/api/admin/models/{model_id}/load",
        dependencies=[Depends(require_admin_token)],
    )
    async def load_model(model_id: str) -> dict:
        return await handle_load_model(
            container,
            model_id=model_id,
        )

    @router.post(
        "/api/admin/models/{model_id}/unload",
        dependencies=[Depends(require_admin_token)],
    )
    async def unload_model(model_id: str) -> dict:
        return await handle_unload_model(
            container,
            model_id=model_id,
        )

    @router.post(
        "/api/admin/models",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin_token)],
    )
    async def create_model(payload: dict[str, Any]) -> dict:
        return await handle_create_model(
            container,
            payload=payload,
        )

    @router.get(
        "/api/admin/models/{model_id}",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_model(model_id: str) -> dict:
        return await handle_get_model(
            container,
            model_id=model_id,
        )

    @router.patch(
        "/api/admin/models/{model_id}",
        dependencies=[Depends(require_admin_token)],
    )
    async def update_model(model_id: str, payload: dict) -> dict:
        return await handle_update_model(
            container,
            model_id=model_id,
            payload=payload,
        )

    @router.delete(
        "/api/admin/models/{model_id}",
        dependencies=[Depends(require_admin_token)],
    )
    async def delete_model(model_id: str) -> dict:
        return await handle_delete_model(
            container,
            model_id=model_id,
        )

    return router
