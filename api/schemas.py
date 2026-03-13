from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gen3d.engine.sequence import RequestSequence, TaskStatus, TaskType


class TaskOptions(BaseModel):
    resolution: Literal[512, 1024, 1536] = 1024
    ss_steps: int = 12
    shape_steps: int = 20
    material_steps: int = 12
    ss_guidance_scale: float = 7.5
    shape_guidance_scale: float = 7.5
    material_guidance_scale: float = 3.0
    decimation_target: int = 1_000_000
    texture_size: int = 4096
    mock_failure_stage: Literal[
        "preprocessing",
        "gpu_ss",
        "gpu_shape",
        "gpu_material",
        "exporting",
        "uploading",
    ] | None = None

    model_config = ConfigDict(extra="allow")


class TaskCreateRequest(BaseModel):
    type: Literal["image_to_3d"]
    image_url: str
    callback_url: str | None = None
    idempotency_key: str | None = None
    options: TaskOptions = Field(default_factory=TaskOptions)


class TaskError(BaseModel):
    message: str
    failed_stage: str | None = None


class ArtifactPayload(BaseModel):
    type: str
    url: str | None = None
    created_at: datetime | None = None
    size_bytes: int | None = None
    backend: str | None = None
    content_type: str | None = None
    expires_at: datetime | None = None


class TaskArtifactsResponse(BaseModel):
    artifacts: list[ArtifactPayload] = Field(default_factory=list)


class TaskResponse(BaseModel):
    task_id: str = Field(serialization_alias="taskId")
    status: TaskStatus
    progress: int
    current_stage: str = Field(serialization_alias="currentStage")
    queue_position: int | None = Field(default=None, serialization_alias="queuePosition")
    estimated_wait_seconds: int | None = Field(
        default=None,
        serialization_alias="estimatedWaitSeconds",
    )
    estimated_finish_at: datetime | None = Field(
        default=None,
        serialization_alias="estimatedFinishAt",
    )
    created_at: datetime = Field(serialization_alias="createdAt")
    started_at: datetime | None = Field(default=None, serialization_alias="startedAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    error: TaskError | None = None
    artifacts: list[ArtifactPayload] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_sequence(cls, sequence: RequestSequence) -> "TaskResponse":
        error = None
        if sequence.error_message is not None:
            error = TaskError(
                message=sequence.error_message,
                failed_stage=sequence.failed_stage,
            )
        return cls(
            task_id=sequence.task_id,
            status=sequence.status,
            progress=sequence.progress,
            current_stage=sequence.current_stage,
            queue_position=sequence.queue_position,
            estimated_wait_seconds=sequence.estimated_wait_seconds,
            estimated_finish_at=sequence.estimated_finish_at,
            created_at=sequence.created_at,
            started_at=sequence.started_at,
            updated_at=sequence.updated_at,
            error=error,
            artifacts=[ArtifactPayload(**artifact) for artifact in sequence.artifacts],
        )


class TaskCreateResponse(BaseModel):
    task_id: str = Field(serialization_alias="taskId")
    status: TaskStatus
    queue_position: int | None = Field(default=None, serialization_alias="queuePosition")
    estimated_wait_seconds: int | None = Field(
        default=None,
        serialization_alias="estimatedWaitSeconds",
    )
    estimated_finish_at: datetime | None = Field(
        default=None,
        serialization_alias="estimatedFinishAt",
    )

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_sequence(cls, sequence: RequestSequence) -> "TaskCreateResponse":
        return cls(
            task_id=sequence.task_id,
            status=sequence.status,
            queue_position=sequence.queue_position,
            estimated_wait_seconds=sequence.estimated_wait_seconds,
            estimated_finish_at=sequence.estimated_finish_at,
        )


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
    service: str


def task_type_from_request(value: str) -> TaskType:
    return TaskType(value)
