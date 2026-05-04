from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status

from cubie.api.routers.auth import build_require_admin_token
from cubie.api.schemas import (
    AdminHfEndpointResponse,
    AdminHfEndpointUpdateRequest,
    AdminHfLoginRequest,
    AdminHfStatusResponse,
)
from cubie.core import hf as _hf_helpers
from cubie.core.hf import (
    current_hf_endpoint,
    ensure_hf_client_available,
    normalize_hf_endpoint,
    resolve_hf_status,
    set_hf_endpoint,
)

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


HF_ENDPOINT_SETTING_KEY = "hfEndpoint"


def build_admin_hf_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.get(
        "/api/admin/hf-status",
        response_model=AdminHfStatusResponse,
        dependencies=[Depends(require_admin_token)],
    )
    async def get_hf_status() -> AdminHfStatusResponse:
        logged_in, username = resolve_hf_status()
        return AdminHfStatusResponse(
            logged_in=logged_in,
            username=username,
            endpoint=current_hf_endpoint(),
        )

    @router.patch(
        "/api/admin/hf-endpoint",
        response_model=AdminHfEndpointResponse,
        dependencies=[Depends(require_admin_token)],
    )
    async def update_hf_endpoint(
        payload: AdminHfEndpointUpdateRequest,
    ) -> AdminHfEndpointResponse:
        try:
            normalized_endpoint = normalize_hf_endpoint(payload.endpoint, strict=True)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        set_hf_endpoint(normalized_endpoint)
        await container.settings_store.set(HF_ENDPOINT_SETTING_KEY, normalized_endpoint)
        return AdminHfEndpointResponse(endpoint=normalized_endpoint)

    @router.post(
        "/api/admin/hf-login",
        response_model=AdminHfStatusResponse,
        dependencies=[Depends(require_admin_token)],
    )
    async def login_hf(payload: AdminHfLoginRequest) -> AdminHfStatusResponse:
        ensure_hf_client_available()
        token = str(payload.token or "").strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="token must be a non-empty string",
            )
        # Keep login calls pinned to the current mirror endpoint.
        set_hf_endpoint(current_hf_endpoint())
        try:
            _hf_helpers._hf_login(token=token)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        logged_in, username = resolve_hf_status()
        return AdminHfStatusResponse(
            logged_in=logged_in,
            username=username,
            endpoint=current_hf_endpoint(),
        )

    @router.post(
        "/api/admin/hf-logout",
        response_model=AdminHfStatusResponse,
        dependencies=[Depends(require_admin_token)],
    )
    async def logout_hf() -> AdminHfStatusResponse:
        ensure_hf_client_available()
        try:
            _hf_helpers._hf_logout()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        return AdminHfStatusResponse(
            logged_in=False,
            username=None,
            endpoint=current_hf_endpoint(),
        )

    return router
