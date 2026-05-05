from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cubie.auth.api_key_store import USER_KEY_SCOPE
from cubie.auth.helpers import extract_bearer_token, is_valid_token

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


_auth_scheme = HTTPBearer(auto_error=False)


def build_require_bearer_token(
    container: AppContainer,
) -> Callable[..., Awaitable[str]]:
    async def require_bearer_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(_auth_scheme),
    ) -> str:
        key = await container.api_key_store.validate_token(
            extract_bearer_token(credentials),
            required_scope=USER_KEY_SCOPE,
        )
        if key is not None:
            return str(key["key_id"])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return require_bearer_token


def build_require_scoped_api_key(
    container: AppContainer,
    scope: str,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def require_scoped_api_key(
        credentials: HTTPAuthorizationCredentials | None = Depends(_auth_scheme),
    ) -> dict[str, Any]:
        key = await container.api_key_store.validate_token(
            extract_bearer_token(credentials),
            required_scope=scope,
        )
        if key is not None:
            return key
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return require_scoped_api_key


def build_require_admin_token(
    container: AppContainer,
) -> Callable[..., Awaitable[None]]:
    async def require_admin_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(_auth_scheme),
    ) -> None:
        if is_valid_token(
            extract_bearer_token(credentials),
            container.config.admin_token,
        ):
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return require_admin_token
