from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from cubie.api.helpers.auth import build_require_admin_token
from cubie.api.helpers.deps import build_dep_response_rows

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_admin_deps_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.get(
        "/api/admin/deps",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_deps() -> list[dict]:
        dep_rows = await container.dep_instance_store.list_all()
        return build_dep_response_rows(
            provider_type="",
            dep_rows=dep_rows,
        )

    return router
