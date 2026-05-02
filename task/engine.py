from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import structlog
from gen3d.artifact.store import ArtifactStore, ArtifactStoreOperationError
from gen3d.core.observability.metrics import increment_webhook_total, set_queue_depth
from gen3d.core.pagination import CursorPageResult
from gen3d.core.security import (
    TokenRateLimiter,
    validate_callback_url,
    validate_image_url,
)
from gen3d.model.registry import ModelRegistry, ModelRegistryLoadError
from gen3d.task.eta import PROCESSING_STATUSES, decorate_sequence_eta
from gen3d.task.events import (
    TaskEventQueues,
    build_event_payload,
    build_event_queues,
    is_terminal_event_status,
    is_terminal_task_status,
    publish_event,
    replay_event_payloads,
    subscribe_event_queue,
    unsubscribe_event_queue,
)
from gen3d.task.pipeline import (
    CancelRequestResult,
    PipelineCoordinator,
    PipelineQueueFullError,
)
from gen3d.task.sequence import (
    TERMINAL_STATUSES,
    RequestSequence,
    TaskStatus,
    TaskType,
    utcnow,
)
from gen3d.task.store import TaskIdempotencyConflictError, TaskStore
from gen3d.task.webhook import (
    WebhookSender,
    build_default_webhook_sender,
    send_webhook_with_retries,
)
from structlog.contextvars import bound_contextvars

if TYPE_CHECKING:
    from gen3d.model.scheduler import ModelScheduler


@dataclass(slots=True)
class TaskCancelResult:
    outcome: str
    sequence: RequestSequence | None


class AsyncGen3DEngine:
    _CLEANUP_CONCURRENCY = 5
    _CLEANUP_BATCH_SIZE = 20

    @staticmethod
    def normalize_startup_models(startup_models: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                str(model_name).strip().lower()
                for model_name in startup_models
                if str(model_name).strip()
            )
        )

    def __init__(self, *, task_store: TaskStore, pipeline: PipelineCoordinator, model_registry: ModelRegistry, artifact_store: ArtifactStore | None = None, model_scheduler: "ModelScheduler | None" = None, webhook_sender: WebhookSender | None = None, webhook_timeout_seconds: float = 2.0, webhook_max_retries: int = 3, provider_mode: str = "mock", allowed_callback_domains: tuple[str, ...] = (), rate_limiter: TokenRateLimiter | None = None, parallel_slots: int = 1, queue_max_size: int = 20, uploads_dir: Path = Path("./data/uploads"), worker_poll_interval_seconds: float = 0.01, startup_models: tuple[str, ...] = ()) -> None:
        self._task_store = task_store
        self._pipeline = pipeline
        self._model_registry = model_registry
        self._artifact_store = artifact_store
        self._model_scheduler = model_scheduler
        self._started = False
        self._worker_count = max(int(parallel_slots), 1)
        self._queue_capacity = self._worker_count + max(int(queue_max_size), 0)
        self._worker_poll_interval_seconds = max(float(worker_poll_interval_seconds), 0.01)
        self._event_queues: TaskEventQueues = build_event_queues()
        self._cleanup_event = asyncio.Event()
        self._cleanup_semaphore = asyncio.Semaphore(self._CLEANUP_CONCURRENCY)
        self._cleanup_worker_task: asyncio.Task[None] | None = None
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._webhook_sender = webhook_sender or build_default_webhook_sender(webhook_timeout_seconds)
        self._webhook_max_retries = max(int(webhook_max_retries), 0)
        self._allow_local_inputs = provider_mode.strip().lower() == "mock"
        self._allowed_callback_domains = allowed_callback_domains
        self._rate_limiter = rate_limiter
        self._uploads_dir = Path(uploads_dir)
        self._startup_models = self.normalize_startup_models(startup_models)
        self._logger = structlog.get_logger(__name__)
        self._pipeline.add_listener(self.publish_update)

    async def start(self) -> None:
        if self._started:
            return
        await self._pipeline.start()
        if await self.has_pending_cleanups():
            self._cleanup_event.set()
        self._cleanup_worker_task = asyncio.create_task(self.run_cleanup_worker())
        self._worker_tasks = [
            asyncio.create_task(self.run_worker_loop(worker_index), name=f"cubie3d-worker-{worker_index}")
            for worker_index in range(self._worker_count)
        ]
        set_queue_depth(await self._task_store.count_queued_tasks())
        self._started = True
        for model_name in self._startup_models:
            self.start_startup_prewarm(model_name)

    def set_startup_models(self, startup_models: tuple[str, ...]) -> None:
        self._startup_models = self.normalize_startup_models(startup_models)

    async def stop(self) -> None:
        if not self._started:
            return
        for worker_task in self._worker_tasks:
            worker_task.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()
        if self._cleanup_worker_task is not None:
            self._cleanup_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_worker_task
            self._cleanup_worker_task = None
        await self._pipeline.stop()
        await self._model_registry.close()
        self._started = False
        set_queue_depth(0)

    async def submit_task(self, *, task_type: TaskType, image_url: str, options: dict, callback_url: str | None = None, idempotency_key: str | None = None, key_id: str | None = None, model: str = "trellis") -> tuple[RequestSequence, bool]:
        image_url = validate_image_url(image_url, allow_local_inputs=self._allow_local_inputs)
        callback_url = validate_callback_url(callback_url, allowed_domains=self._allowed_callback_domains)
        normalized_model = str(model).strip().lower() or "trellis"
        rate_limit_key = key_id or "anonymous"
        if self._rate_limiter is not None:
            await self._rate_limiter.record_request(rate_limit_key)
        if idempotency_key:
            existing = await self._task_store.get_task_by_idempotency_key(idempotency_key)
            if existing is not None:
                with bound_contextvars(task_id=existing.task_id):
                    self._logger.info("task.reused", idempotency_key=idempotency_key, status=existing.status.value)
                await self.decorate_sequence(existing)
                return existing, False
        if self._rate_limiter is not None:
            await self._rate_limiter.check_concurrent_tasks(rate_limit_key)
        if await self._task_store.count_incomplete_tasks() >= self._queue_capacity:
            raise PipelineQueueFullError("pipeline queue is full")

        sequence = RequestSequence.new_task(model=normalized_model, input_url=image_url, options=options, callback_url=callback_url, idempotency_key=idempotency_key, key_id=key_id, task_type=task_type)
        try:
            await self._task_store.create_task(sequence)
        except TaskIdempotencyConflictError as exc:
            existing = exc.existing_sequence
            with bound_contextvars(task_id=existing.task_id):
                self._logger.info(
                    "task.reused_after_conflict", idempotency_key=idempotency_key, status=existing.status.value
                )
            await self.decorate_sequence(existing)
            return existing, False
        if self._rate_limiter is not None:
            await self._rate_limiter.register_task(rate_limit_key, sequence.task_id)
        sequence.queue_position = await self._task_store.get_queue_position(sequence.task_id) or 1
        stage_stats = await self._task_store.get_stage_stats(sequence.model)
        decorate_sequence_eta(sequence, worker_count=self._worker_count, queue_position=sequence.queue_position, stage_stats=stage_stats, now=utcnow())
        set_queue_depth(await self._task_store.count_queued_tasks())
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info(
                "task.submitted", task_type=task_type.value, callback_enabled=bool(callback_url), idempotency_key=idempotency_key, key_id=key_id, model=sequence.model
            )
        return sequence, True

    def update_queue_capacity(self, queue_max_size: int) -> None:
        self._queue_capacity = self._worker_count + max(int(queue_max_size), 0)

    async def list_tasks(self, *, key_id: str | None, limit: int = 20, before=None) -> CursorPageResult[RequestSequence]:
        page = await self._task_store.list_tasks(key_id=key_id, limit=limit, before=before)
        for sequence in page.items:
            await self.decorate_sequence(sequence)
        return page

    async def delete_task(self, task_id: str) -> RequestSequence | None:
        sequence = await self._task_store.get_task(task_id)
        if sequence is None:
            return None
        deleted = await self._task_store.soft_delete_task(task_id, deleted_at=utcnow())
        if not deleted:
            return None
        self._cleanup_event.set()
        return sequence

    async def has_pending_cleanups(self) -> bool:
        pending = await self._task_store.list_pending_cleanups(limit=1)
        return bool(pending)

    async def run_cleanup_worker(self) -> None:
        while True:
            await self._cleanup_event.wait()
            self._cleanup_event.clear()
            while True:
                pending_task_ids = await self._task_store.list_pending_cleanups(
                    limit=self._CLEANUP_BATCH_SIZE
                )
                if not pending_task_ids:
                    break
                await asyncio.gather(
                    *(self.cleanup_single_task(task_id) for task_id in pending_task_ids)
                )

    async def cleanup_single_task(self, task_id: str) -> None:
        async with self._cleanup_semaphore:
            sequence = await self._task_store.get_task(task_id, include_deleted=True)
            if self._artifact_store is not None:
                try:
                    await self._artifact_store.delete_artifacts(task_id)
                except ArtifactStoreOperationError as exc:
                    with bound_contextvars(task_id=task_id):
                        self._logger.warning(
                            "task.artifact_cleanup_failed",
                            stage=exc.stage_name,
                            error=str(exc),
                        )
                except Exception as exc:  # pragma: no cover - defensive guard
                    with bound_contextvars(task_id=task_id):
                        self._logger.warning(
                            "task.artifact_cleanup_failed",
                            stage="cleanup",
                            error=str(exc),
                        )
            if sequence is not None:
                await self.cleanup_uploaded_input(sequence.input_url, task_id=task_id)
            try:
                await self._task_store.mark_cleanup_done(task_id)
            except Exception as exc:  # pragma: no cover - defensive guard
                with bound_contextvars(task_id=task_id):
                    self._logger.warning(
                        "task.artifact_cleanup_mark_done_failed",
                        error=str(exc),
                    )

    async def cleanup_uploaded_input(self, input_url: str, *, task_id: str) -> None:
        parsed = urlparse(input_url)
        if parsed.scheme != "upload":
            return
        upload_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
        if not upload_id:
            return
        try:
            matches = await asyncio.to_thread(
                lambda: list(self._uploads_dir.glob(f"{upload_id}.*"))
            )
            for match in matches:
                if match.exists():
                    await asyncio.to_thread(match.unlink)
        except Exception as exc:  # pragma: no cover - defensive guard
            with bound_contextvars(task_id=task_id):
                self._logger.warning(
                    "task.upload_cleanup_failed",
                    error=str(exc),
                    input_url=input_url,
                )

    async def get_task(self, task_id: str) -> RequestSequence | None:
        sequence = await self._task_store.get_task(task_id)
        if sequence is None:
            return None
        await self.decorate_sequence(sequence)
        return sequence

    async def get_artifacts(self, task_id: str) -> list[dict[str, Any]] | None:
        sequence = await self.get_task(task_id)
        if sequence is None:
            return None
        if sequence.artifacts:
            return sequence.artifacts
        if self._artifact_store is None:
            return []
        return await self._artifact_store.list_artifacts(task_id)

    async def cancel_task(self, task_id: str) -> TaskCancelResult:
        result: CancelRequestResult = await self._pipeline.cancel_task(task_id)
        return TaskCancelResult(outcome=result.outcome, sequence=result.sequence)

    @property
    def ready(self) -> bool:
        return self._started and self._model_registry.has_ready_model()

    async def stream_events(
        self,
        task_id: str,
        *,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[dict[str, Any] | None]:
        """Yield event payloads for the given task.

        Yields ``None`` as a heartbeat sentinel every *heartbeat_interval*
        seconds when no real event arrives.  Callers must filter out ``None``
        values and treat them as keep-alive signals (e.g. send an SSE comment).
        This prevents reverse-proxy idle-timeout disconnections during long
        inference gaps (e.g. between GPU_SS and GPU_SHAPE).
        """
        queue = subscribe_event_queue(self._event_queues, task_id)
        try:
            history = await self._task_store.list_task_events(task_id)
            for replayed_payload in replay_event_payloads(task_id=task_id, history=history):
                yield replayed_payload
            current = await self._task_store.get_task(task_id)
            if current is not None and is_terminal_task_status(current.status):
                return
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                except asyncio.TimeoutError:
                    yield None  # heartbeat — no event within interval
                    continue
                yield payload
                if is_terminal_event_status(payload.get("status")):
                    break
        finally:
            unsubscribe_event_queue(self._event_queues, task_id=task_id, queue=queue)

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

    def start_startup_prewarm(self, model_name: str) -> None:
        if not self._started:
            return
        self._model_registry.load(model_name)
        self._logger.info("model.prewarm_scheduled", model_name=model_name)

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
        decorate_sequence_eta(sequence, worker_count=self._worker_count, queue_position=queue_position, stage_stats=stage_stats, now=utcnow())

    async def publish_update(self, sequence: RequestSequence, event: str, metadata: dict[str, Any]) -> None:
        with bound_contextvars(task_id=sequence.task_id):
            payload = build_event_payload(sequence, event=event, metadata=metadata)
            publish_event(self._event_queues, task_id=sequence.task_id, payload=payload)
            if self._rate_limiter is not None and sequence.status in TERMINAL_STATUSES:
                await self._rate_limiter.release_task(sequence.task_id)
            if event in {"succeeded", "failed"} and sequence.callback_url:
                await send_webhook_with_retries(sequence=sequence, sender=self._webhook_sender, append_task_event=self._task_store.append_task_event, record_result=increment_webhook_total, logger=self._logger, max_retries=self._webhook_max_retries, sleep=asyncio.sleep)
