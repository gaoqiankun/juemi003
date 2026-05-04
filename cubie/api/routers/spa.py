from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


WEB_DIST_DIR = Path(__file__).resolve().parents[3] / "web" / "dist"
SPA_INDEX_PATH = WEB_DIST_DIR / "index.html"


class SPAStaticFiles(StaticFiles):
    def __init__(self, *args, spa_index_path: Path, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._spa_index_path = spa_index_path

    async def get_response(self, path: str, scope: Scope) -> Response:
        fallback = None
        normalized_path = path.strip("/.")
        request_path = f"/{normalized_path}" if normalized_path else "/"
        if (
            scope.get("method") in {"GET", "HEAD"}
            and self._spa_index_path.is_file()
            and should_serve_static_spa_route(request_path)
        ):
            fallback = FileResponse(self._spa_index_path)
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND or fallback is None:
                raise
            return fallback
        if response.status_code == status.HTTP_404_NOT_FOUND and fallback is not None:
            return fallback
        return response


def should_serve_static_spa_route(path: str) -> bool:
    normalized = path.strip() or "/"
    if normalized in {"/", ""}:
        return True
    if normalized.startswith("/api/") or normalized.startswith("/v1/"):
        return False
    if normalized in {"/health", "/readiness", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"}:
        return False
    if normalized.startswith("/assets/"):
        return False
    return "." not in normalized.rsplit("/", 1)[-1]


def build_spa_router(container: AppContainer) -> APIRouter:
    _ = container
    router = APIRouter()

    @router.get("/", include_in_schema=False)
    async def spa_root() -> Response:
        if SPA_INDEX_PATH.is_file():
            return FileResponse(SPA_INDEX_PATH)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/static", include_in_schema=False)
    async def static_root_redirect() -> Response:
        return RedirectResponse(url="/", status_code=status.HTTP_308_PERMANENT_REDIRECT)

    @router.get("/static/{spa_path:path}", include_in_schema=False)
    async def static_compat_redirect(spa_path: str) -> Response:
        target = f"/{spa_path.lstrip('/')}" if spa_path else "/"
        return RedirectResponse(url=target, status_code=status.HTTP_308_PERMANENT_REDIRECT)

    return router


def mount_spa_static(app: FastAPI) -> None:
    app.mount(
        "/",
        SPAStaticFiles(
            directory=str(WEB_DIST_DIR),
            check_dir=False,
            spa_index_path=SPA_INDEX_PATH,
        ),
        name="spa",
    )
