from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.types import Scope

from cubie.api.helpers.artifacts import (
    extract_artifact_filename,
    resolve_dev_local_model_path,
)
from cubie.core.config import ServingConfig

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
PROXY_REQUEST_HEADER_EXCLUSIONS = HOP_BY_HOP_HEADERS | {"host", "content-length"}


def should_proxy_dev_request(request: Request, config: ServingConfig) -> bool:
    if config.dev_proxy_target is None:
        return False
    path = request.url.path
    if (
        path.startswith("/static")
        or path.startswith("/assets/")
        or path == "/favicon.svg"
    ):
        return False
    if resolve_dev_local_model_path(config, extract_artifact_filename(path)) is not None:
        return False
    return (
        path.startswith("/v1/")
        or path.startswith("/api/")
        or path
        in {
            "/health",
            "/readiness",
            "/ready",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        }
    )


def rewrite_legacy_api_path(scope: Scope) -> None:
    path = scope.get("path", "")
    if not isinstance(path, str):
        return
    if path == "/api/v1" or path.startswith("/api/v1/"):
        rewritten_path = path[4:]
        scope["path"] = rewritten_path
        scope["raw_path"] = rewritten_path.encode("utf-8")


async def forward_dev_proxy_request(
    *,
    request: Request,
    proxy_client: httpx.AsyncClient,
    proxy_target: str | None,
) -> Response:
    if proxy_target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    upstream_request = proxy_client.build_request(
        method=request.method,
        url=build_dev_proxy_url(proxy_target, request),
        headers=build_proxy_request_headers(request),
        content=await request.body(),
    )
    try:
        upstream_response = await proxy_client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"dev proxy request failed: {exc}",
        ) from exc

    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=build_proxy_response_headers(upstream_response),
        background=BackgroundTask(upstream_response.aclose),
    )


def build_dev_proxy_url(proxy_target: str, request: Request) -> str:
    target = urlsplit(proxy_target)
    target_path = target.path.rstrip("/")
    if not target_path.startswith("/") and target_path:
        target_path = f"/{target_path}"
    combined_path = (
        f"{target_path}{request.url.path}" if target_path else request.url.path
    )
    if not combined_path.startswith("/"):
        combined_path = f"/{combined_path}"
    return urlunsplit(
        (
            target.scheme,
            target.netloc,
            combined_path,
            request.url.query,
            "",
        )
    )


def build_proxy_request_headers(request: Request) -> list[tuple[str, str]]:
    headers: list[tuple[str, str]] = []
    for name, value in request.headers.raw:
        decoded_name = name.decode("latin-1")
        if decoded_name.lower() in PROXY_REQUEST_HEADER_EXCLUSIONS:
            continue
        headers.append((decoded_name, value.decode("latin-1")))
    return headers


def build_proxy_response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS
    }
