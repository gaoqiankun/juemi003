from __future__ import annotations

import asyncio
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import structlog
from gen3d.artifact.store import ArtifactStore, ArtifactStoreOperationError
from gen3d.core.observability.metrics import observe_stage_duration
from gen3d.model.base import GenerationResult, ModelProviderExecutionError
from gen3d.model.registry import ModelRegistry, ModelRuntime
from gen3d.stage.base import BaseStage, StageExecutionError, StageUpdateHandler
from gen3d.stage.export.preview_renderer_service import PreviewRendererServiceProtocol
from gen3d.task.sequence import RequestSequence, TaskStatus
from structlog.contextvars import bound_contextvars


class ExportStage(BaseStage):
    name = "export"

    def __init__(
        self,
        *,
        model_registry: ModelRegistry,
        artifact_store: ArtifactStore,
        preview_renderer_service: PreviewRendererServiceProtocol,
        task_store,
        delay_ms: int = 0,
    ) -> None:
        self._model_registry = model_registry
        self._artifact_store = artifact_store
        self._preview_renderer_service = preview_renderer_service
        self._task_store = task_store
        self._delay_seconds = max(delay_ms, 0) / 1000
        self._logger = structlog.get_logger(__name__)

    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
        started_at = time.perf_counter()
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info("stage.started", stage=self.name, model=sequence.model)
            try:
                runtime = await self.prepare(sequence, on_update)
                artifact, preview_artifact, upload_started_at = await self.export_and_upload(
                    runtime, sequence, on_update,
                )
                await self._task_store.update_stage_stats(
                    model=sequence.model,
                    stage=TaskStatus.UPLOADING.value,
                    duration_seconds=time.perf_counter() - upload_started_at,
                )
                await self.finalize(sequence, artifact, preview_artifact)
                self.log_completed(sequence, started_at)
                await self.emit_succeeded(sequence, on_update)
                return sequence
            except Exception as exc:
                self.log_failed(exc, started_at)
                raise
            finally:
                observe_stage_duration(
                    stage=self.name,
                    duration_seconds=time.perf_counter() - started_at,
                )

    async def prepare(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None,
    ) -> ModelRuntime:
        runtime = self._model_registry.get_runtime(sequence.model)
        sequence.transition_to(
            TaskStatus.EXPORTING,
            current_stage=TaskStatus.EXPORTING.value,
        )
        await self._emit_update(sequence, on_update)
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        self.check_mock_failure(sequence, TaskStatus.EXPORTING.value)
        if not isinstance(sequence.generation_result, GenerationResult):
            raise StageExecutionError(
                stage_name=TaskStatus.EXPORTING.value,
                message="missing generation result for export",
            )
        return runtime

    async def export_and_upload(
        self,
        runtime: ModelRuntime,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None,
    ) -> tuple[dict, dict | None, float]:
        export_started_at = time.perf_counter()
        preview_staging_path: Path | None = None
        async with self._artifact_store.create_staging_path(
            sequence.task_id,
            "model.glb",
        ) as staging_path:
            try:
                await self.export_glb(runtime, sequence, Path(staging_path))
                preview_staging_path = await self.render_preview(Path(staging_path))
                await self._task_store.update_stage_stats(
                    model=sequence.model,
                    stage=TaskStatus.EXPORTING.value,
                    duration_seconds=time.perf_counter() - export_started_at,
                )
                sequence.transition_to(
                    TaskStatus.UPLOADING,
                    current_stage=TaskStatus.UPLOADING.value,
                )
                await self._emit_update(sequence, on_update)
                self.check_mock_failure(sequence, TaskStatus.UPLOADING.value)
                upload_started_at = time.perf_counter()
                artifact = await self.publish_glb(sequence, Path(staging_path))
                preview_artifact: dict | None = None
                if preview_staging_path is not None and preview_staging_path.exists():
                    preview_artifact = await self.publish_preview(
                        sequence.task_id,
                        preview_staging_path,
                    )
                return artifact, preview_artifact, upload_started_at
            finally:
                if preview_staging_path is not None and preview_staging_path.exists():
                    await asyncio.to_thread(self.delete_if_exists, preview_staging_path)

    async def export_glb(
        self,
        runtime: ModelRuntime,
        sequence: RequestSequence,
        staging_path: Path,
    ) -> None:
        with self.translate_provider_errors(
            TaskStatus.EXPORTING.value,
            generic_fallback_message="failed to export GLB artifact",
        ):
            await asyncio.to_thread(
                runtime.provider.export_glb,
                sequence.generation_result,
                staging_path,
                sequence.options,
            )
            sequence.generation_result = None  # Release CUDA IPC tensors

    async def render_preview(self, model_path: Path) -> Path | None:
        preview_staging_path: Path | None = None
        try:
            preview_staging_path = await asyncio.to_thread(
                self.create_preview_temp_path,
                model_path,
            )
            preview_png = await self._preview_renderer_service.render_preview_png(
                model_path=model_path,
            )
            await asyncio.to_thread(preview_staging_path.write_bytes, preview_png)
            return preview_staging_path
        except Exception as exc:
            self._logger.warning(
                "stage.preview_render_failed",
                stage=self.name,
                error=str(exc),
            )
            if preview_staging_path is not None and preview_staging_path.exists():
                await asyncio.to_thread(self.delete_if_exists, preview_staging_path)
            return None

    async def publish_glb(
        self,
        sequence: RequestSequence,
        staging_path: Path,
    ) -> dict:
        with self.translate_provider_errors(TaskStatus.UPLOADING.value):
            return await self._artifact_store.publish_artifact(
                task_id=sequence.task_id,
                artifact_type="glb",
                file_name="model.glb",
                staging_path=staging_path,
                content_type="model/gltf-binary",
            )

    async def publish_preview(
        self,
        task_id: str,
        staging_path: Path,
    ) -> dict | None:
        try:
            return await self._artifact_store.publish_artifact(
                task_id=task_id,
                artifact_type="preview",
                file_name="preview.png",
                staging_path=staging_path,
                content_type="image/png",
            )
        except Exception as exc:
            self._logger.warning(
                "stage.preview_render_failed",
                stage=self.name,
                error=str(exc),
            )
            return None

    async def finalize(
        self,
        sequence: RequestSequence,
        artifact: dict,
        preview_artifact: dict | None,
    ) -> None:
        sequence.artifacts = self.merge_artifacts(
            primary_artifacts=[artifact],
            supplemental_artifacts=[preview_artifact] if preview_artifact is not None else [],
            existing_artifacts=sequence.artifacts,
        )
        with self.translate_provider_errors(TaskStatus.UPLOADING.value):
            await self._artifact_store.replace_artifacts(
                sequence.task_id,
                sequence.artifacts,
            )
        sequence.transition_to(
            TaskStatus.SUCCEEDED,
            current_stage=TaskStatus.SUCCEEDED.value,
        )

    def log_completed(self, sequence: RequestSequence, started_at: float) -> None:
        self._logger.info(
            "stage.completed",
            stage=self.name,
            duration_seconds=round(time.perf_counter() - started_at, 6),
            artifact_count=len(sequence.artifacts),
        )

    def log_failed(self, exc: BaseException, started_at: float) -> None:
        self._logger.warning(
            "stage.failed",
            stage=self.name,
            duration_seconds=round(time.perf_counter() - started_at, 6),
            error=str(exc),
        )

    async def emit_succeeded(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None,
    ) -> None:
        await self._emit_update(
            sequence,
            on_update,
            event="succeeded",
            metadata={
                "status": sequence.status.value,
                "stage": TaskStatus.UPLOADING.value,
                "artifacts": sequence.artifacts,
            },
        )

    @contextmanager
    def translate_provider_errors(
        self,
        stage_name: str,
        generic_fallback_message: str | None = None,
    ) -> Iterator[None]:
        try:
            yield
        except StageExecutionError:
            raise
        except (ModelProviderExecutionError, ArtifactStoreOperationError) as exc:
            raise StageExecutionError(exc.stage_name, str(exc)) from exc
        except Exception as exc:
            if generic_fallback_message is None:
                raise
            raise StageExecutionError(
                stage_name=stage_name,
                message=f"{generic_fallback_message}: {exc}",
            ) from exc

    def check_mock_failure(self, sequence: RequestSequence, stage: str) -> None:
        if sequence.options.get("mock_failure_stage") != stage:
            return
        raise StageExecutionError(
            stage_name=stage,
            message=f"mock failure injected at {stage}",
        )

    @staticmethod
    def merge_artifacts(
        *,
        primary_artifacts: list[dict],
        supplemental_artifacts: list[dict],
        existing_artifacts: list[dict],
    ) -> list[dict]:
        merged: list[dict] = []
        seen_urls: set[str] = set()
        for artifact in [*primary_artifacts, *supplemental_artifacts, *existing_artifacts]:
            if not artifact:
                continue
            artifact_url = str(artifact.get("url") or "")
            if artifact_url in seen_urls:
                continue
            seen_urls.add(artifact_url)
            merged.append(artifact)
        return merged

    @staticmethod
    def create_preview_temp_path(model_path: Path) -> Path:
        with tempfile.NamedTemporaryFile(
            dir=model_path.parent,
            prefix="preview.",
            suffix=".png",
            delete=False,
        ) as handle:
            return Path(handle.name)

    @staticmethod
    def delete_if_exists(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
