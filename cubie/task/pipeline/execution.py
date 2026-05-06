from __future__ import annotations

from structlog.contextvars import bound_contextvars

from cubie.stage.base import StageExecutionError
from cubie.task.sequence import RequestSequence, TaskStatus


class ExecutionMixin:
    async def run_sequence(self, sequence: RequestSequence) -> RequestSequence:
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info(
                "task.processing_started",
                current_stage=sequence.current_stage,
                model=sequence.model,
            )
            stage_index = 0
            while stage_index < len(self._stages):
                try:
                    sequence, stage_index = await self.execute_one_stage(sequence, stage_index)
                except StageExecutionError as exc:
                    await self.mark_stage_failed(
                        sequence,
                        stage_name=exc.stage_name,
                        message=str(exc),
                    )
                    break
                except Exception as exc:  # pragma: no cover - defensive fallback
                    stage = self._stages[stage_index]
                    self._logger.exception(
                        "task.processing_failed_unexpected",
                        stage=stage.name,
                        error=str(exc),
                    )
                    await self.mark_stage_failed(
                        sequence,
                        stage_name=stage.name,
                        message=str(exc),
                    )
                    break
                if self.is_terminal(sequence):
                    break
        return sequence

    async def execute_one_stage(
        self,
        sequence: RequestSequence,
        stage_index: int,
    ) -> tuple[RequestSequence, int]:
        stage = self._stages[stage_index]
        if self.can_run_with_inference_lease(stage_index):
            export_stage = self._stages[stage_index + 1]
            sequence = await self.run_gpu_export_with_lease(
                sequence,
                gpu_stage=stage,
                export_stage=export_stage,
            )
            return sequence, stage_index + 2
        sequence = await stage.run(sequence, on_update=self.publish_update)
        return sequence, stage_index + 1

    @staticmethod
    def is_terminal(sequence: RequestSequence) -> bool:
        return sequence.status in {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }

    def can_run_with_inference_lease(self, stage_index: int) -> bool:
        if self._inference_allocator is None or self._model_registry is None:
            return False
        if stage_index + 1 >= len(self._stages):
            return False
        stage = self._stages[stage_index]
        next_stage = self._stages[stage_index + 1]
        return stage.name == "gpu" and next_stage.name == "export"
