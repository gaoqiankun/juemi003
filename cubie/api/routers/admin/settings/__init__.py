from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from cubie.api.helpers.auth import build_require_admin_token

from . import get as admin_settings_get
from . import update as admin_settings_update

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_admin_settings_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.get(
        "/api/admin/settings",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_settings() -> dict:
        return await admin_settings_get.get_settings(container)

    @router.patch(
        "/api/admin/settings",
        dependencies=[Depends(require_admin_token)],
    )
    async def update_settings(payload: dict) -> dict:
        return await admin_settings_update.update_settings(payload, container)

    return router
