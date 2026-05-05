from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response, status

from cubie.api.helpers.auth import build_require_admin_token
from cubie.api.schemas import (
    AdminApiKeyCreateRequest,
    AdminApiKeyCreateResponse,
    AdminApiKeyListItem,
    AdminApiKeySetActiveRequest,
    PrivilegedApiKeyCreateRequest,
    PrivilegedApiKeyCreateResponse,
    PrivilegedApiKeyListItem,
)

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


async def handle_create_privileged_key(
    container: AppContainer,
    payload: PrivilegedApiKeyCreateRequest,
) -> PrivilegedApiKeyCreateResponse:
    try:
        api_key = await container.api_key_store.create_privileged_key(
            label=payload.label,
            scope=payload.scope,
            allowed_ips=payload.allowed_ips,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PrivilegedApiKeyCreateResponse(**api_key)


async def handle_list_privileged_keys(
    container: AppContainer,
) -> list[PrivilegedApiKeyListItem]:
    api_keys = await container.api_key_store.list_privileged_keys()
    return [PrivilegedApiKeyListItem(**api_key) for api_key in api_keys]


async def handle_delete_privileged_key(
    container: AppContainer,
    key_id: str,
) -> Response:
    revoked = await container.api_key_store.revoke_privileged_key(key_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="privileged token not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def handle_create_admin_key(
    container: AppContainer,
    payload: AdminApiKeyCreateRequest,
) -> AdminApiKeyCreateResponse:
    try:
        api_key = await container.api_key_store.create_user_key(payload.label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminApiKeyCreateResponse(**api_key)


async def handle_list_admin_keys(container: AppContainer) -> list[AdminApiKeyListItem]:
    api_keys = await container.api_key_store.list_user_keys()
    return [AdminApiKeyListItem(**api_key) for api_key in api_keys]


async def handle_set_admin_key_active(
    container: AppContainer,
    key_id: str,
    payload: AdminApiKeySetActiveRequest,
) -> AdminApiKeyListItem:
    updated = await container.api_key_store.set_active(
        key_id,
        payload.is_active,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="api key not found",
        )
    api_key = await container.api_key_store.get_user_key(key_id)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="api key not found",
        )
    return AdminApiKeyListItem(**api_key)


async def handle_delete_admin_key(
    container: AppContainer,
    key_id: str,
) -> Response:
    deleted = await container.api_key_store.revoke_user_key(key_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="api key not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def handle_get_keys_stats(container: AppContainer) -> dict:
    stats = await container.api_key_store.get_usage_stats()
    return stats


def build_admin_keys_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.post(
        "/api/admin/privileged-keys",
        response_model=PrivilegedApiKeyCreateResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin_token)],
    )
    async def create_privileged_key(
        payload: PrivilegedApiKeyCreateRequest,
    ) -> PrivilegedApiKeyCreateResponse:
        return await handle_create_privileged_key(container, payload)

    @router.get(
        "/api/admin/privileged-keys",
        response_model=list[PrivilegedApiKeyListItem],
        dependencies=[Depends(require_admin_token)],
    )
    async def list_privileged_keys() -> list[PrivilegedApiKeyListItem]:
        return await handle_list_privileged_keys(container)

    @router.delete(
        "/api/admin/privileged-keys/{key_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_admin_token)],
    )
    async def delete_privileged_key(key_id: str) -> Response:
        return await handle_delete_privileged_key(container, key_id)

    @router.post(
        "/api/admin/keys",
        response_model=AdminApiKeyCreateResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin_token)],
    )
    async def create_admin_key(
        payload: AdminApiKeyCreateRequest,
    ) -> AdminApiKeyCreateResponse:
        return await handle_create_admin_key(container, payload)

    @router.get(
        "/api/admin/keys",
        response_model=list[AdminApiKeyListItem],
        dependencies=[Depends(require_admin_token)],
    )
    async def list_admin_keys() -> list[AdminApiKeyListItem]:
        return await handle_list_admin_keys(container)

    @router.patch(
        "/api/admin/keys/{key_id}",
        response_model=AdminApiKeyListItem,
        dependencies=[Depends(require_admin_token)],
    )
    async def set_admin_key_active(
        key_id: str,
        payload: AdminApiKeySetActiveRequest,
    ) -> AdminApiKeyListItem:
        return await handle_set_admin_key_active(container, key_id, payload)

    @router.delete(
        "/api/admin/keys/{key_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_admin_token)],
    )
    async def delete_admin_key(key_id: str) -> Response:
        return await handle_delete_admin_key(container, key_id)

    @router.get(
        "/api/admin/keys/stats",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_keys_stats() -> dict:
        return await handle_get_keys_stats(container)

    return router
