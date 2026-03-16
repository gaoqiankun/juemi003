from __future__ import annotations

import asyncio
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
                async with self._artifact_store.create_staging_path(
                    sequence.task_id,
                    "model.glb",
                ) as staging_path:
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
                await self._task_store.update_stage_stats(
                    model=sequence.model,
                    stage=TaskStatus.UPLOADING.value,
                    duration_seconds=time.perf_counter() - upload_started_at,
                )
                sequence.artifacts = [artifact]
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
