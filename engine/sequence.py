from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskType(str, Enum):
    IMAGE_TO_3D = "image_to_3d"


class TaskStatus(str, Enum):
    SUBMITTED = "submitted"
    PREPROCESSING = "preprocessing"
    GPU_QUEUED = "gpu_queued"
    GPU_SS = "gpu_ss"
    GPU_SHAPE = "gpu_shape"
    GPU_MATERIAL = "gpu_material"
    EXPORTING = "exporting"
    UPLOADING = "uploading"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


DEFAULT_PROGRESS_BY_STATUS: dict[TaskStatus, int] = {
    TaskStatus.SUBMITTED: 0,
    TaskStatus.PREPROCESSING: 1,
    TaskStatus.GPU_QUEUED: 5,
    TaskStatus.GPU_SS: 25,
    TaskStatus.GPU_SHAPE: 60,
    TaskStatus.GPU_MATERIAL: 90,
    TaskStatus.EXPORTING: 95,
    TaskStatus.UPLOADING: 99,
    TaskStatus.SUCCEEDED: 100,
    TaskStatus.FAILED: 0,
    TaskStatus.CANCELLED: 0,
}

TERMINAL_STATUSES = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}

ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.SUBMITTED: {
        TaskStatus.PREPROCESSING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.PREPROCESSING: {
        TaskStatus.GPU_QUEUED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.GPU_QUEUED: {
        TaskStatus.GPU_SS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.GPU_SS: {
        TaskStatus.GPU_SHAPE,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.GPU_SHAPE: {
        TaskStatus.GPU_MATERIAL,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.GPU_MATERIAL: {
        TaskStatus.EXPORTING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.EXPORTING: {
        TaskStatus.UPLOADING,
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.UPLOADING: {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


@dataclass(slots=True)
class RequestSequence:
    task_id: str
    task_type: TaskType
    input_url: str
    options: dict[str, Any]
    callback_url: str | None = None
    idempotency_key: str | None = None
    key_id: str | None = None
    status: TaskStatus = TaskStatus.SUBMITTED
    progress: int = 0
    current_stage: str = TaskStatus.SUBMITTED.value
    queue_position: int | None = None
    estimated_wait_seconds: int | None = None
    estimated_finish_at: datetime | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None
    failed_stage: str | None = None
    retry_count: int = 0
    assigned_worker_id: str | None = None
    prepared_input: dict[str, Any] | None = None
    generation_result: Any | None = None
    created_at: datetime = field(default_factory=utcnow)
    queued_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = field(default_factory=utcnow)
    deleted_at: datetime | None = None

    @classmethod
    def new_task(
        cls,
        *,
        input_url: str,
        options: dict[str, Any],
        callback_url: str | None = None,
        idempotency_key: str | None = None,
        key_id: str | None = None,
        task_type: TaskType = TaskType.IMAGE_TO_3D,
    ) -> "RequestSequence":
        now = utcnow()
        return cls(
            task_id=str(uuid4()),
            task_type=task_type,
            input_url=input_url,
            options=options,
            callback_url=callback_url,
            idempotency_key=idempotency_key,
            key_id=key_id,
            progress=DEFAULT_PROGRESS_BY_STATUS[TaskStatus.SUBMITTED],
            current_stage=TaskStatus.SUBMITTED.value,
            created_at=now,
            queued_at=now,
            updated_at=now,
        )

    def transition_to(
        self,
        status: TaskStatus,
        *,
        progress: int | None = None,
        current_stage: str | None = None,
        queue_position: int | None = None,
        estimated_wait_seconds: int | None = None,
        estimated_finish_at: datetime | None = None,
        error_message: str | None = None,
        failed_stage: str | None = None,
    ) -> None:
        if status != self.status and status not in ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"invalid transition: {self.status.value} -> {status.value}")

        now = utcnow()
        self.status = status
        self.progress = progress if progress is not None else DEFAULT_PROGRESS_BY_STATUS[status]
        self.current_stage = current_stage or status.value
        self.queue_position = queue_position
        self.estimated_wait_seconds = estimated_wait_seconds
        self.estimated_finish_at = estimated_finish_at
        self.updated_at = now

        if status == TaskStatus.PREPROCESSING and self.started_at is None:
            self.started_at = now

        if status in TERMINAL_STATUSES:
            self.completed_at = now

        if error_message is not None:
            self.error_message = error_message
        if failed_stage is not None:
            self.failed_stage = failed_stage
