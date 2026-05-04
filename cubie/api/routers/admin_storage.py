from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from cubie.api.routers.auth import build_require_admin_token

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_admin_storage_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.get(
        "/api/admin/storage/stats",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_storage_stats() -> dict:
        return await container.weight_manager.get_storage_stats()

    @router.get(
        "/api/admin/storage/orphans",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_storage_orphans() -> list:
        return await container.weight_manager.list_orphans()

    @router.get(
        "/api/admin/storage/breakdown",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_storage_breakdown() -> dict:
        return await container.weight_manager.get_storage_breakdown()

    @router.delete(
        "/api/admin/storage/orphans",
        dependencies=[Depends(require_admin_token)],
    )
    async def clean_storage_orphans() -> dict:
        return await container.weight_manager.clean_orphans()

    return router
