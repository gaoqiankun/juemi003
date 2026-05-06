from __future__ import annotations

import asyncio
from typing import Any

from structlog.contextvars import bound_contextvars

from cubie.core.observability.metrics import increment_webhook_total, set_queue_depth
from cubie.model.registry import ModelRegistryLoadError
from cubie.task.eta import PROCESSING_STATUSES, decorate_sequence_eta
from cubie.task.events import build_event_payload, publish_event
from cubie.task.sequence import (
    TERMINAL_STATUSES,
    RequestSequence,
    TaskStatus,
    utcnow,
)
from cubie.task.webhook import send_webhook_with_retries


class WorkerLoopMixin:
    async def run_worker_loop(self, worker_index: int) -> None:
        worker_id = f"pipeline-worker-{worker_index}"
        while True:
            try:
                sequence = await self.claim_next_task(worker_id)
                if sequence is None:
                    continue
                if not await self.load_model_for_task(sequence):
                    continue
                await self.run_task_pipeline(sequence)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.exception(
                    "worker.loop_failed",
                    worker_id=worker_id,
                    error=str(exc),
                )
                await asyncio.sleep(self._worker_poll_interval_seconds)
            finally:
                set_queue_depth(await self._task_store.count_queued_tasks())

    async def claim_next_task(self, worker_id: str) -> RequestSequence | None:
        sequence = await self._task_store.claim_next_queued_task(worker_id)
        set_queue_depth(await self._task_store.count_queued_tasks())
        if sequence is None:
            await asyncio.sleep(self._worker_poll_interval_seconds)
            return None
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info(
                "task.claimed",
                worker_id=worker_id,
                model=sequence.model,
            )
        return sequence

    async def load_model_for_task(self, sequence: RequestSequence) -> bool:
        try:
            if self._model_scheduler is not None:
                await self._model_scheduler.request_load(sequence.model)
                if (
                    not self._model_scheduler.enabled
                    and self._model_registry.get_state(sequence.model) == "not_loaded"
                ):
                    # In mock mode, scheduler is disabled. Keep a direct load fallback
                    # so legacy alias tasks (e.g. "trellis") do not fail.
                    self._model_registry.load(sequence.model)
            else:
                # Fallback for unit-test wiring where scheduler is not injected.
                self._model_registry.load(sequence.model)
            await self._model_registry.wait_ready(sequence.model)
            return True
        except ModelRegistryLoadError as exc:
            await self.fail_task_with_load_error(sequence, exc)
            return False

    async def fail_task_with_load_error(
        self,
        sequence: RequestSequence,
        exc: ModelRegistryLoadError,
    ) -> None:
        latest = await self._task_store.get_task(sequence.task_id) or sequence
        latest.transition_to(
            TaskStatus.FAILED,
            current_stage=TaskStatus.QUEUED.value,
            error_message=str(exc),
            failed_stage=TaskStatus.QUEUED.value,
        )
        await self._pipeline.publish_update(
            latest,
            "failed",
            {
                "status": latest.status.value,
                "stage": TaskStatus.QUEUED.value,
                "message": str(exc),
            },
        )

    async def run_task_pipeline(self, sequence: RequestSequence) -> None:
        latest = await self._task_store.get_task(sequence.task_id)
        if latest is None or latest.status in TERMINAL_STATUSES:
            return
        completed = await self._pipeline.run_sequence(latest)
        if self._model_scheduler is not None:
            await self._model_scheduler.on_task_completed(completed.model)

    async def decorate_sequence(self, sequence: RequestSequence) -> None:
        if self._artifact_store is not None and not sequence.artifacts:
            sequence.artifacts = await self._artifact_store.list_artifacts(sequence.task_id)
        queue_position: int | None = None
        stage_stats: dict[str, dict[str, float | int]] | None = None
        if sequence.status == TaskStatus.QUEUED:
            queue_position = await self._task_store.get_queue_position(sequence.task_id)
            stage_stats = await self._task_store.get_stage_stats(sequence.model)
        elif sequence.status in PROCESSING_STATUSES:
            stage_stats = await self._task_store.get_stage_stats(sequence.model)
        decorate_sequence_eta(
            sequence,
            worker_count=self._worker_count,
            queue_position=queue_position,
            stage_stats=stage_stats,
            now=utcnow(),
        )

    async def publish_update(
        self,
        sequence: RequestSequence,
        event: str,
        metadata: dict[str, Any],
    ) -> None:
        with bound_contextvars(task_id=sequence.task_id):
            payload = build_event_payload(sequence, event=event, metadata=metadata)
            publish_event(self._event_queues, task_id=sequence.task_id, payload=payload)
            if self._rate_limiter is not None and sequence.status in TERMINAL_STATUSES:
                await self._rate_limiter.release_task(sequence.task_id)
            if event in {"succeeded", "failed"} and sequence.callback_url:
                await send_webhook_with_retries(
                    sequence=sequence,
                    sender=self._webhook_sender,
                    append_task_event=self._task_store.append_task_event,
                    record_result=increment_webhook_total,
                    logger=self._logger,
                    max_retries=self._webhook_max_retries,
                    sleep=asyncio.sleep,
                )
