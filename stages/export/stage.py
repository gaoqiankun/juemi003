from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import structlog
from structlog.contextvars import bound_contextvars

from gen3d.engine.model_registry import ModelRegistry
from gen3d.engine.sequence import RequestSequence, TaskStatus
from gen3d.model.base import GenerationResult, ModelProviderExecutionError
from gen3d.observability.metrics import observe_stage_duration
from gen3d.stages.base import BaseStage, StageExecutionError, StageUpdateHandler
from gen3d.storage.artifact_store import ArtifactStore, ArtifactStoreOperationError


class ExportStage(BaseStage):
    name = "export"

    def __init__(
        self,
        *,
        model_registry: ModelRegistry,
        artifact_store: ArtifactStore,
        task_store,
        delay_ms: int = 0,
    ) -> None:
        self._model_registry = model_registry
        self._artifact_store = artifact_store
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
                runtime = self._model_registry.get_runtime(sequence.model)
                sequence.transition_to(
                    TaskStatus.EXPORTING,
                    current_stage=TaskStatus.EXPORTING.value,
                )
                await self._emit_update(sequence, on_update)

                if self._delay_seconds:
                    await asyncio.sleep(self._delay_seconds)

                if sequence.options.get("mock_failure_stage") == TaskStatus.EXPORTING.value:
                    raise StageExecutionError(
                        stage_name=TaskStatus.EXPORTING.value,
                        message="mock failure injected at exporting",
                    )
                if not isinstance(sequence.generation_result, GenerationResult):
                    raise StageExecutionError(
                        stage_name=TaskStatus.EXPORTING.value,
                        message="missing generation result for export",
                    )

                export_started_at = time.perf_counter()
                preview_artifact: dict | None = None
                preview_staging_path: Path | None = None
                async with self._artifact_store.create_staging_path(
                    sequence.task_id,
                    "model.glb",
                ) as staging_path:
                    try:
                        try:
                            await asyncio.to_thread(
                                runtime.provider.export_glb,
                                sequence.generation_result,
                                Path(staging_path),
                                sequence.options,
                            )
                        except ModelProviderExecutionError as exc:
                            raise StageExecutionError(exc.stage_name, str(exc)) from exc
                        except Exception as exc:
                            raise StageExecutionError(
                                stage_name=TaskStatus.EXPORTING.value,
                                message=f"failed to export GLB artifact: {exc}",
                            ) from exc

                        try:
                            preview_staging_path = await asyncio.to_thread(
                                self._create_preview_temp_path,
                                Path(staging_path),
                            )
                            await asyncio.to_thread(
                                self._render_preview_png,
                                Path(staging_path),
                                preview_staging_path,
                            )
                        except Exception as exc:
                            self._logger.warning(
                                "stage.preview_render_failed",
                                stage=self.name,
                                error=str(exc),
                            )
                            if preview_staging_path is not None and preview_staging_path.exists():
                                await asyncio.to_thread(
                                    self._delete_if_exists,
                                    preview_staging_path,
                                )
                            preview_staging_path = None

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

                        if sequence.options.get("mock_failure_stage") == TaskStatus.UPLOADING.value:
                            raise StageExecutionError(
                                stage_name=TaskStatus.UPLOADING.value,
                                message="mock failure injected at uploading",
                            )

                        upload_started_at = time.perf_counter()
                        try:
                            artifact = await self._artifact_store.publish_artifact(
                                task_id=sequence.task_id,
                                artifact_type="glb",
                                file_name="model.glb",
                                staging_path=Path(staging_path),
                                content_type="model/gltf-binary",
                            )
                        except ArtifactStoreOperationError as exc:
                            raise StageExecutionError(exc.stage_name, str(exc)) from exc
                        if preview_staging_path is not None and preview_staging_path.exists():
                            try:
                                preview_artifact = await self._publish_preview_artifact(
                                    sequence.task_id,
                                    preview_staging_path,
                                )
                            except Exception as exc:
                                self._logger.warning(
                                    "stage.preview_render_failed",
                                    stage=self.name,
                                    error=str(exc),
                                )
                    finally:
                        if preview_staging_path is not None and preview_staging_path.exists():
                            await asyncio.to_thread(self._delete_if_exists, preview_staging_path)
                await self._task_store.update_stage_stats(
                    model=sequence.model,
                    stage=TaskStatus.UPLOADING.value,
                    duration_seconds=time.perf_counter() - upload_started_at,
                )
                sequence.artifacts = self._merge_artifacts(
                    primary_artifacts=[artifact],
                    supplemental_artifacts=[preview_artifact] if preview_artifact is not None else [],
                    existing_artifacts=sequence.artifacts,
                )
                try:
                    await self._artifact_store.replace_artifacts(
                        sequence.task_id,
                        sequence.artifacts,
                    )
                except ArtifactStoreOperationError as exc:
                    raise StageExecutionError(exc.stage_name, str(exc)) from exc
                sequence.transition_to(
                    TaskStatus.SUCCEEDED,
                    current_stage=TaskStatus.SUCCEEDED.value,
                )
                duration_seconds = time.perf_counter() - started_at
                self._logger.info(
                    "stage.completed",
                    stage=self.name,
                    duration_seconds=round(duration_seconds, 6),
                    artifact_count=len(sequence.artifacts),
                )
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
                return sequence
            except Exception as exc:
                duration_seconds = time.perf_counter() - started_at
                self._logger.warning(
                    "stage.failed",
                    stage=self.name,
                    duration_seconds=round(duration_seconds, 6),
                    error=str(exc),
                )
                raise
            finally:
                observe_stage_duration(
                    stage=self.name,
                    duration_seconds=time.perf_counter() - started_at,
                )

    async def _publish_preview_artifact(
        self,
        task_id: str,
        staging_path: Path,
    ) -> dict:
        try:
            return await self._artifact_store.publish_artifact(
                task_id=task_id,
                artifact_type="preview",
                file_name="preview.png",
                staging_path=staging_path,
                content_type="image/png",
            )
        except ArtifactStoreOperationError as exc:
            raise StageExecutionError(exc.stage_name, str(exc)) from exc

    @staticmethod
    def _merge_artifacts(
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

    @classmethod
    def _render_preview_png(
        cls,
        model_path: Path,
        output_path: Path,
    ) -> None:
        timeout_seconds = 3
        try:
            pythonpath_entries = [str(Path(__file__).resolve().parents[3])]
            existing_pythonpath = os.environ.get("PYTHONPATH")
            if existing_pythonpath:
                pythonpath_entries.append(existing_pythonpath)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "gen3d.stages.export.preview_renderer",
                    str(model_path),
                    str(output_path),
                ],
                capture_output=True,
                check=True,
                env={
                    **os.environ,
                    "PYTHONPATH": os.pathsep.join(pythonpath_entries),
                },
                text=True,
                timeout=timeout_seconds,
            )
            _ = completed
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"preview renderer timed out after {timeout_seconds} seconds"
            ) from exc
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "").strip()
            if not details:
                details = f"preview renderer exited with code {exc.returncode}"
            raise RuntimeError(details) from exc

    @staticmethod
    def _create_preview_temp_path(model_path: Path) -> Path:
        with tempfile.NamedTemporaryFile(
            dir=model_path.parent,
            prefix="preview.",
            suffix=".png",
            delete=False,
        ) as handle:
            return Path(handle.name)

    @staticmethod
    def _delete_if_exists(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
