from __future__ import annotations

from structlog.contextvars import bound_contextvars

from cubie.task.pipeline import RecoverySummary
from cubie.task.sequence import RequestSequence, TaskStatus, utcnow


class RecoveryMixin:
    async def recover_incomplete_tasks(self) -> RecoverySummary:
        summary = RecoverySummary()
        for sequence in await self._task_store.list_incomplete_tasks():
            await self.recover_one_task(sequence, summary)
        return summary

    async def recover_one_task(
        self,
        sequence: RequestSequence,
        summary: RecoverySummary,
    ) -> None:
        summary.scanned += 1
        age_seconds = max(
            (utcnow() - sequence.created_at).total_seconds(),
            0.0,
        )
        with bound_contextvars(task_id=sequence.task_id):
            if age_seconds > self._task_timeout_seconds:
                summary.failed_timeout += 1
                await self.recover_as_timeout(sequence, age_seconds)
                return
            if sequence.status in {TaskStatus.QUEUED, TaskStatus.PREPROCESSING}:
                summary.requeued += 1
                await self.recover_as_requeue(sequence, age_seconds)
                return
            summary.failed_interrupted += 1
            await self.recover_as_interrupted(sequence, age_seconds)

    async def recover_as_timeout(
        self,
        sequence: RequestSequence,
        age_seconds: float,
    ) -> None:
        self._logger.warning(
            "task.recovered_as_failed",
            recovery_action="timeout",
            previous_status=sequence.status.value,
            current_stage=sequence.current_stage,
            task_age_seconds=round(age_seconds, 6),
        )
        await self.fail_recovered_task(
            sequence,
            message="task exceeded TASK_TIMEOUT_SECONDS before service recovery",
            recovery_action="timeout",
        )

    async def recover_as_requeue(
        self,
        sequence: RequestSequence,
        age_seconds: float,
    ) -> None:
        self._logger.info(
            "task.requeued_after_restart",
            previous_status=sequence.status.value,
            current_stage=sequence.current_stage,
            task_age_seconds=round(age_seconds, 6),
        )
        await self._task_store.requeue_task(sequence.task_id)

    async def recover_as_interrupted(
        self,
        sequence: RequestSequence,
        age_seconds: float,
    ) -> None:
        self._logger.warning(
            "task.recovered_as_failed",
            recovery_action="interrupted",
            previous_status=sequence.status.value,
            current_stage=sequence.current_stage,
            task_age_seconds=round(age_seconds, 6),
        )
        await self.fail_recovered_task(
            sequence,
            message="服务重启，任务中断",
            recovery_action="interrupted",
        )

    async def fail_recovered_task(
        self,
        sequence: RequestSequence,
        *,
        message: str,
        recovery_action: str,
    ) -> None:
        failed_stage = sequence.current_stage or sequence.status.value
        sequence.transition_to(
            TaskStatus.FAILED,
            current_stage=failed_stage,
            error_message=message,
            failed_stage=failed_stage,
        )
        await self.publish_update(
            sequence,
            "failed",
            {
                "status": sequence.status.value,
                "stage": failed_stage,
                "message": message,
                "recovery_action": recovery_action,
            },
        )
