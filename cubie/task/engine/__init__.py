from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from cubie.artifact.store import ArtifactStore
from cubie.core.security import TokenRateLimiter
from cubie.model.registry import ModelRegistry
from cubie.task.events import TaskEventQueues, build_event_queues
from cubie.task.pipeline import PipelineCoordinator
from cubie.task.sequence import RequestSequence
from cubie.task.store import TaskStore
from cubie.task.webhook import WebhookSender, build_default_webhook_sender

if TYPE_CHECKING:
    from cubie.model.scheduler import ModelScheduler


@dataclass(slots=True)
class TaskCancelResult:
    outcome: str
    sequence: RequestSequence | None


def normalize_startup_models(startup_models: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(model_name).strip().lower()
            for model_name in startup_models
            if str(model_name).strip()
        )
    )


from cubie.task.engine.cleanup import CleanupMixin  # noqa: E402
from cubie.task.engine.lifecycle import LifecycleMixin  # noqa: E402
from cubie.task.engine.prewarm import PrewarmMixin  # noqa: E402
from cubie.task.engine.tasks import TasksMixin  # noqa: E402
from cubie.task.engine.worker_loop import WorkerLoopMixin  # noqa: E402

__all__ = (
    "AsyncGen3DEngine",
    "TaskCancelResult",
    "normalize_startup_models",
)


class AsyncGen3DEngine(
    LifecycleMixin,
    TasksMixin,
    WorkerLoopMixin,
    CleanupMixin,
    PrewarmMixin,
):
    _CLEANUP_CONCURRENCY = 5
    _CLEANUP_BATCH_SIZE = 20

    normalize_startup_models = staticmethod(normalize_startup_models)

    def __init__(
        self,
        *,
        task_store: TaskStore,
        pipeline: PipelineCoordinator,
        model_registry: ModelRegistry,
        artifact_store: ArtifactStore | None = None,
        model_scheduler: "ModelScheduler | None" = None,
        webhook_sender: WebhookSender | None = None,
        webhook_timeout_seconds: float = 2.0,
        webhook_max_retries: int = 3,
        provider_mode: str = "mock",
        allowed_callback_domains: tuple[str, ...] = (),
        rate_limiter: TokenRateLimiter | None = None,
        parallel_slots: int = 1,
        queue_max_size: int = 20,
        uploads_dir: Path = Path("./data/uploads"),
        worker_poll_interval_seconds: float = 0.01,
        startup_models: tuple[str, ...] = (),
    ) -> None:
        self._task_store = task_store
        self._pipeline = pipeline
        self._model_registry = model_registry
        self._artifact_store = artifact_store
        self._model_scheduler = model_scheduler
        self._started = False
        self._worker_count = max(int(parallel_slots), 1)
        self._queue_capacity = self._worker_count + max(int(queue_max_size), 0)
        self._worker_poll_interval_seconds = max(
            float(worker_poll_interval_seconds),
            0.01,
        )
        self._event_queues: TaskEventQueues = build_event_queues()
        self._cleanup_event = asyncio.Event()
        self._cleanup_semaphore = asyncio.Semaphore(self._CLEANUP_CONCURRENCY)
        self._cleanup_worker_task: asyncio.Task[None] | None = None
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._webhook_sender = webhook_sender or build_default_webhook_sender(
            webhook_timeout_seconds
        )
        self._webhook_max_retries = max(int(webhook_max_retries), 0)
        self._allow_local_inputs = provider_mode.strip().lower() == "mock"
        self._allowed_callback_domains = allowed_callback_domains
        self._rate_limiter = rate_limiter
        self._uploads_dir = Path(uploads_dir)
        self._startup_models = self.normalize_startup_models(startup_models)
        self._logger = structlog.get_logger(__name__)
        self._pipeline.add_listener(self.publish_update)
