from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse

from cubie.api.helpers.auth import build_require_bearer_token
from cubie.api.schemas import (
    CursorPaginationParams,
    TaskArtifactsResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskListResponse,
    TaskResponse,
)

from .artifacts import handle_download_artifact
from .handlers import (
    handle_cancel_task,
    handle_create_task,
    handle_delete_task,
    handle_get_artifacts,
    handle_get_task,
    handle_list_tasks,
    handle_task_events,
)

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def get_cursor_pagination_params(
    limit: int = Query(default=20, ge=1, le=50),
    before: datetime | None = Query(default=None),
) -> CursorPaginationParams:
    return CursorPaginationParams(limit=limit, before=before)


def build_tasks_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_bearer_token = build_require_bearer_token(container)

    @router.post(
        "/v1/tasks",
        response_model=TaskCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_task(
        payload: TaskCreateRequest,
        response: Response,
        key_id: str = Depends(require_bearer_token),
    ) -> TaskCreateResponse:
        return await handle_create_task(container, payload, response, key_id)

    @router.get(
        "/v1/tasks",
        response_model=TaskListResponse,
    )
    async def list_tasks(
        key_id: str = Depends(require_bearer_token),
        pagination: CursorPaginationParams = Depends(get_cursor_pagination_params),
    ) -> TaskListResponse:
        return await handle_list_tasks(
            container,
            key_id=key_id,
            pagination=pagination,
        )

    @router.delete(
        "/v1/tasks/{task_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_task(
        task_id: str,
        key_id: str = Depends(require_bearer_token),
    ) -> Response:
        return await handle_delete_task(
            container,
            task_id=task_id,
            key_id=key_id,
        )

    @router.get(
        "/v1/tasks/{task_id}",
        response_model=TaskResponse,
        dependencies=[Depends(require_bearer_token)],
    )
    async def get_task(task_id: str) -> TaskResponse:
        return await handle_get_task(container, task_id=task_id)

    @router.get(
        "/v1/tasks/{task_id}/events",
        dependencies=[Depends(require_bearer_token)],
    )
    async def task_events(task_id: str) -> StreamingResponse:
        return await handle_task_events(container, task_id=task_id)

    @router.post(
        "/v1/tasks/{task_id}/cancel",
        response_model=TaskResponse,
        dependencies=[Depends(require_bearer_token)],
    )
    async def cancel_task(task_id: str) -> TaskResponse:
        return await handle_cancel_task(container, task_id=task_id)

    @router.get(
        "/v1/tasks/{task_id}/artifacts",
        response_model=TaskArtifactsResponse,
        dependencies=[Depends(require_bearer_token)],
    )
    async def get_artifacts(task_id: str) -> TaskArtifactsResponse:
        return await handle_get_artifacts(container, task_id=task_id)

    @router.get(
        "/v1/tasks/{task_id}/artifacts/{filename}",
    )
    async def download_artifact(
        task_id: str,
        filename: str,
    ) -> Response:
        return await handle_download_artifact(
            container,
            task_id=task_id,
            filename=filename,
        )

    return router
