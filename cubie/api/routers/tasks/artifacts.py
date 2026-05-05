from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import HTTPException, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from cubie.api.helpers.artifacts import (
    artifact_exists,
    build_artifact_download_headers,
    cleanup_temporary_artifact,
    dispatch_preview_render,
    resolve_dev_local_model_path,
)
from cubie.task.sequence import TaskStatus

if TYPE_CHECKING:
    from cubie.api.server import AppContainer
    from cubie.artifact.store import ArtifactStore
    from cubie.stage.export.preview_renderer_service import (
        PreviewRendererServiceProtocol,
    )


ARTIFACT_STREAM_CHUNK_SIZE = 1024 * 1024


async def stream_artifact_body(body: Any) -> AsyncIterator[bytes]:
    try:
        while True:
            chunk = await asyncio.to_thread(
                body.read,
                ARTIFACT_STREAM_CHUNK_SIZE,
            )
            if not chunk:
                break
            yield chunk
    finally:
        await asyncio.to_thread(body.close)


async def build_streaming_artifact_response(
    container: AppContainer,
    *,
    task_id: str,
    filename: str,
) -> StreamingResponse | None:
    streaming_download = await container.artifact_store.open_streaming_download(
        task_id,
        filename,
    )
    if streaming_download is None:
        return None

    headers = build_artifact_download_headers(
        file_name=streaming_download.file_name,
        content_length=streaming_download.content_length,
        etag=streaming_download.etag,
    )
    return StreamingResponse(
        stream_artifact_body(streaming_download.body),
        media_type=streaming_download.content_type,
        headers=headers,
    )


async def dispatch_preview_render_if_possible(
    *,
    artifact_store: ArtifactStore,
    preview_renderer_service: PreviewRendererServiceProtocol,
    task_id: str,
    filename: str,
) -> None:
    if Path(filename).name.lower() != "preview.png":
        return
    if not await artifact_exists(
        artifact_store,
        task_id=task_id,
        file_name="model.glb",
    ):
        return
    dispatch_preview_render(
        task_id,
        artifact_store,
        preview_renderer_service,
    )


async def handle_download_artifact(
    container: AppContainer,
    *,
    task_id: str,
    filename: str,
) -> Response:
    local_model_path = resolve_dev_local_model_path(container.config, filename)
    if local_model_path is not None:
        return FileResponse(
            path=local_model_path,
            filename=Path(filename).name,
            media_type="model/gltf-binary",
        )

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
    streaming_response = await build_streaming_artifact_response(
        container,
        task_id=task_id,
        filename=filename,
    )
    if streaming_response is not None:
        return streaming_response

    artifact_download = await container.artifact_store.prepare_download(
        task_id,
        filename,
    )
    if artifact_download is None:
        await dispatch_preview_render_if_possible(
            artifact_store=container.artifact_store,
            preview_renderer_service=container.preview_renderer_service,
            task_id=task_id,
            filename=filename,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="artifact not found",
        )
    artifact_path, content_type, is_temporary = artifact_download
    background = BackgroundTask(cleanup_temporary_artifact, artifact_path) if is_temporary else None
    return FileResponse(
        path=artifact_path,
        filename=Path(filename).name,
        media_type=content_type,
        background=background,
    )
