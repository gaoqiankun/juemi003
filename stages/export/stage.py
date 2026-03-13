from __future__ import annotations

import asyncio
from pathlib import Path

from gen3d.engine.sequence import RequestSequence, TaskStatus
from gen3d.model.base import BaseModelProvider, GenerationResult, ModelProviderExecutionError
from gen3d.stages.base import BaseStage, StageExecutionError, StageUpdateHandler
from gen3d.storage.artifact_store import ArtifactStore, ArtifactStoreOperationError


class ExportStage(BaseStage):
    name = "export"

    def __init__(
        self,
        *,
        provider: BaseModelProvider,
        artifact_store: ArtifactStore,
        delay_ms: int = 0,
    ) -> None:
        self._provider = provider
        self._artifact_store = artifact_store
        self._delay_seconds = max(delay_ms, 0) / 1000

    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
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

        async with self._artifact_store.create_staging_path(
            sequence.task_id,
            "model.glb",
        ) as staging_path:
            try:
                await asyncio.to_thread(
                    self._provider.export_glb,
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
        sequence.artifacts = [artifact]
        sequence.transition_to(
            TaskStatus.SUCCEEDED,
            current_stage=TaskStatus.SUCCEEDED.value,
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
