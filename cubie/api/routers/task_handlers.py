from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import HTTPException, Response, status
from fastapi.responses import StreamingResponse

from cubie.api.schemas import (
    CursorPaginationParams,
    TaskArtifactsResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskListResponse,
    TaskResponse,
    TaskSummary,
    task_type_from_request,
)
from cubie.auth.helpers import safe_record_usage
from cubie.core.security import (
    RateLimitExceededError,
    TaskSubmissionValidationError,
)
from cubie.task.pipeline import PipelineQueueFullError
from cubie.task.sequence import TERMINAL_STATUSES, TaskStatus

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


async def resolve_normalized_model(
    container: AppContainer,
    payload: TaskCreateRequest,
) -> str:
    requested_model = str(payload.model or "").strip().lower()
    if requested_model:
        return requested_model

    default_model = await container.model_store.get_default_model()
    if default_model is None:
        all_models = await container.model_store.list_models()
        default_model = all_models[0] if all_models else None

    normalized_model = str(default_model.get("id") if default_model else "").strip().lower()
    if not normalized_model:
        raise HTTPException(
            status_code=422,
            detail="no default model configured",
        )
    return normalized_model


async def handle_create_task(
    container: AppContainer,
    payload: TaskCreateRequest,
    response: Response,
    key_id: str,
) -> TaskCreateResponse:
    if not payload.input_url.startswith("upload://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="input_url must start with upload://",
        )
    normalized_model = await resolve_normalized_model(container, payload)
    model_definition = await container.model_store.get_model(normalized_model)
    if model_definition is not None and not bool(model_definition.get("is_enabled")):
        raise HTTPException(
            status_code=422,
            detail="该模型已被管理员禁用",
        )
    try:
        sequence, created = await container.engine.submit_task(
            task_type=task_type_from_request(payload.type),
            image_url=payload.input_url,
            options=payload.options.model_dump(exclude_none=True),
            callback_url=payload.callback_url,
            idempotency_key=payload.idempotency_key,
            key_id=key_id,
            model=normalized_model,
        )
    except TaskSubmissionValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except PipelineQueueFullError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "queue_full",
                "message": str(exc),
            },
        ) from exc
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    asyncio.create_task(safe_record_usage(container.api_key_store, key_id))
    if created:
        asyncio.create_task(
            container.model_scheduler.on_task_queued(normalized_model)
        )
    return TaskCreateResponse.from_sequence(sequence)


async def handle_list_tasks(
    container: AppContainer,
    *,
    key_id: str,
    pagination: CursorPaginationParams,
) -> TaskListResponse:
    page = await container.engine.list_tasks(
        key_id=key_id,
        limit=pagination.limit,
        before=pagination.before,
    )
    return TaskListResponse(
        items=[TaskSummary.from_sequence(task) for task in page.items],
        has_more=page.has_more,
        next_cursor=page.next_cursor,
    )


async def handle_delete_task(
    container: AppContainer,
    *,
    task_id: str,
    key_id: str,
) -> Response:
    sequence = await container.engine.get_task(task_id)
    if sequence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    if sequence.key_id != key_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden",
        )
    if sequence.status not in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="task is not terminal and cannot be deleted",
        )

    deleted = await container.engine.delete_task(task_id)
    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def handle_get_task(
    container: AppContainer,
    *,
    task_id: str,
) -> TaskResponse:
    sequence = await container.engine.get_task(task_id)
    if sequence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    return TaskResponse.from_sequence(sequence)


async def handle_task_events(
    container: AppContainer,
    *,
    task_id: str,
) -> StreamingResponse:
    sequence = await container.engine.get_task(task_id)
    if sequence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )

    async def event_stream():
        async for event in container.engine.stream_events(task_id):
            if event is None:
                yield "event: heartbeat\ndata: {}\n\n"
                continue
            yield (
                f"event: {event['event']}\n"
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def handle_cancel_task(
    container: AppContainer,
    *,
    task_id: str,
) -> TaskResponse:
    result = await container.engine.cancel_task(task_id)
    if result.sequence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    if result.outcome == "already_terminal":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"task already in terminal status: {result.sequence.status.value}",
        )
    if result.outcome == "not_cancellable":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"task cannot be cancelled in status: {result.sequence.status.value}",
        )
    return TaskResponse.from_sequence(result.sequence)


async def handle_get_artifacts(
    container: AppContainer,
    *,
    task_id: str,
) -> TaskArtifactsResponse:
    sequence = await container.engine.get_task(task_id)
    if sequence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    if sequence.status != TaskStatus.SUCCEEDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="artifacts are only available for succeeded tasks",
        )
    artifacts = await container.engine.get_artifacts(task_id)
    return TaskArtifactsResponse(
        artifacts=artifacts or [],
    )
