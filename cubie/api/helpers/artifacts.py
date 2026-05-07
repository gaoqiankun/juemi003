from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import structlog

from cubie.artifact import ArtifactStore
from cubie.stage import ExportStage, PreviewRendererServiceProtocol

_preview_rendering: set[str] = set()
_preview_render_tasks: set[asyncio.Task[None]] = set()
_logger = structlog.get_logger("cubie.api.server")

def cleanup_temporary_artifact(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def artifact_file_name_from_url(value: Any) -> str | None:
    if not value:
        return None
    return Path(urlsplit(str(value)).path).name or None

def artifact_matches_file_name(
    artifact: dict[str, Any],
    file_name: str,
) -> bool:
    return artifact_file_name_from_url(artifact.get("url")) == file_name

async def artifact_exists(
    artifact_store: ArtifactStore,
    *,
    task_id: str,
    file_name: str,
) -> bool:
    if artifact_store.mode == "local":
        return await artifact_store.get_local_artifact_path(task_id, file_name) is not None

    artifacts = await artifact_store.list_artifacts(task_id)
    return any(
        artifact_matches_file_name(artifact, file_name)
        for artifact in artifacts
    )

def merge_preview_artifacts(
    existing_artifacts: list[dict[str, Any]],
    preview_artifact: dict[str, Any],
) -> list[dict[str, Any]]:
    artifacts_without_preview = [
        artifact
        for artifact in existing_artifacts
        if not artifact_matches_file_name(artifact, "preview.png")
    ]
    primary_artifacts = [
        artifact
        for artifact in artifacts_without_preview
        if artifact.get("type") == "glb" or artifact_matches_file_name(artifact, "model.glb")
    ]
    primary_artifact_ids = {id(artifact) for artifact in primary_artifacts}
    remaining_artifacts = [
        artifact
        for artifact in artifacts_without_preview
        if id(artifact) not in primary_artifact_ids
    ]
    return ExportStage.merge_artifacts(
        primary_artifacts=primary_artifacts,
        supplemental_artifacts=[preview_artifact],
        existing_artifacts=remaining_artifacts,
    )

async def render_preview_artifact_on_demand(
    task_id: str,
    artifact_store: ArtifactStore,
    preview_renderer_service: PreviewRendererServiceProtocol,
) -> None:
    model_path: Path | None = None
    preview_staging_path: Path | None = None
    model_is_temporary = False
    try:
        if await artifact_exists(
            artifact_store,
            task_id=task_id,
            file_name="preview.png",
        ):
            return

        existing_artifacts = await artifact_store.list_artifacts(task_id)
        model_download = await artifact_store.prepare_download(task_id, "model.glb")
        if model_download is None:
            return

        model_path, _, model_is_temporary = model_download
        preview_staging_path = await asyncio.to_thread(
            ExportStage.create_preview_temp_path,
            model_path,
        )
        preview_png = await preview_renderer_service.render_preview_png(
            model_path=model_path,
        )
        await asyncio.to_thread(preview_staging_path.write_bytes, preview_png)
        preview_artifact = await artifact_store.publish_artifact(
            task_id=task_id,
            artifact_type="preview",
            file_name="preview.png",
            staging_path=preview_staging_path,
            content_type="image/png",
        )
        await artifact_store.replace_artifacts(
            task_id,
            merge_preview_artifacts(existing_artifacts, preview_artifact),
        )
    except Exception as exc:
        _logger.warning(
            "artifact.preview_render_failed",
            task_id=task_id,
            error=str(exc),
        )
    finally:
        if preview_staging_path is not None and preview_staging_path.exists():
            await asyncio.to_thread(cleanup_temporary_artifact, preview_staging_path)
        if model_path is not None and model_is_temporary:
            await asyncio.to_thread(cleanup_temporary_artifact, model_path)
        _preview_rendering.discard(task_id)

def dispatch_preview_render(
    task_id: str,
    artifact_store: ArtifactStore,
    preview_renderer_service: PreviewRendererServiceProtocol,
) -> None:
    if task_id in _preview_rendering:
        return

    _preview_rendering.add(task_id)
    try:
        task = asyncio.create_task(
            render_preview_artifact_on_demand(
                task_id,
                artifact_store,
                preview_renderer_service,
            ),
        )
    except Exception as exc:
        _preview_rendering.discard(task_id)
        _logger.warning(
            "artifact.preview_render_schedule_failed",
            task_id=task_id,
            error=str(exc),
        )
        return

    _preview_render_tasks.add(task)
    task.add_done_callback(_preview_render_tasks.discard)
