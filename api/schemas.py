from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from gen3d.engine.sequence import RequestSequence, TaskStatus, TaskType
from gen3d.pagination import DEFAULT_CURSOR_PAGE_LIMIT, MAX_CURSOR_PAGE_LIMIT

T = TypeVar("T")


class TaskOptions(BaseModel):
    resolution: Literal[512, 1024, 1536] = 1024
    ss_steps: int = Field(default=12, ge=1, le=64)
    shape_steps: int = Field(default=20, ge=1, le=64)
    material_steps: int = Field(default=12, ge=1, le=64)
    ss_guidance_scale: float = Field(
        default=7.5,
        ge=0.0,
        le=20.0,
        validation_alias=AliasChoices("ss_guidance_scale", "ss_guidance_strength"),
    )
    shape_guidance_scale: float = Field(
        default=7.5,
        ge=0.0,
        le=20.0,
        validation_alias=AliasChoices("shape_guidance_scale", "shape_guidance_strength"),
    )
    material_guidance_scale: float = Field(
        default=3.0,
        ge=0.0,
        le=20.0,
        validation_alias=AliasChoices(
            "material_guidance_scale",
            "material_guidance_strength",
        ),
    )
    decimation_target: int = Field(default=1_000_000, ge=1, le=2_000_000)
    texture_size: int = Field(default=4096, ge=512, le=8192)
    max_num_tokens: int = Field(default=49_152, ge=1_024, le=98_304)
    pipeline_type: Literal["512", "1024", "1024_cascade", "1536_cascade"] | None = None
    aabb: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None
    remesh: bool = True
    remesh_band: int = Field(default=1, ge=0, le=8)
    remesh_project: int = Field(default=0, ge=0, le=8)
    export_verbose: bool = False
    mock_failure_stage: Literal[
        "preprocessing",
        "gpu_ss",
        "gpu_shape",
        "gpu_material",
        "exporting",
        "uploading",
    ] | None = None

    model_config = ConfigDict(extra="forbid")


class TaskCreateRequest(BaseModel):
    type: Literal["image_to_3d"] = "image_to_3d"
    input_url: str = Field(
        validation_alias=AliasChoices("input_url", "image_url"),
    )
    model: str = Field(default="trellis")
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
    model: str
    input_url: str
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
        visible_artifacts = sequence.artifacts if sequence.status == TaskStatus.SUCCEEDED else []
        return cls(
            task_id=sequence.task_id,
            status=sequence.status,
            model=sequence.model,
            input_url=sequence.input_url,
            progress=sequence.progress,
            current_stage=sequence.current_stage,
            queue_position=sequence.queue_position,
            estimated_wait_seconds=sequence.estimated_wait_seconds,
            estimated_finish_at=sequence.estimated_finish_at,
            created_at=sequence.created_at,
            started_at=sequence.started_at,
            updated_at=sequence.updated_at,
            error=error,
            artifacts=[ArtifactPayload(**artifact) for artifact in visible_artifacts],
        )


class TaskCreateResponse(BaseModel):
    task_id: str = Field(serialization_alias="taskId")
    status: TaskStatus
    model: str
    input_url: str
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
            model=sequence.model,
            input_url=sequence.input_url,
            queue_position=sequence.queue_position,
            estimated_wait_seconds=sequence.estimated_wait_seconds,
            estimated_finish_at=sequence.estimated_finish_at,
        )


class TaskSummary(BaseModel):
    task_id: str = Field(serialization_alias="taskId")
    status: TaskStatus
    model: str
    input_url: str
    created_at: datetime = Field(serialization_alias="createdAt")
    finished_at: datetime | None = Field(default=None, serialization_alias="finishedAt")
    artifact_url: str | None = Field(default=None, serialization_alias="artifactUrl")

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_sequence(cls, sequence: RequestSequence) -> "TaskSummary":
        artifact_url = None
        if sequence.status == TaskStatus.SUCCEEDED and sequence.artifacts:
            glb_artifact = next(
                (artifact for artifact in sequence.artifacts if artifact.get("type") == "glb"),
                sequence.artifacts[0],
            )
            artifact_url = glb_artifact.get("url")
        return cls(
            task_id=sequence.task_id,
            status=sequence.status,
            model=sequence.model,
            input_url=sequence.input_url,
            created_at=sequence.created_at,
            finished_at=sequence.completed_at,
            artifact_url=artifact_url,
        )


class CursorPage(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    has_more: bool = Field(serialization_alias="hasMore")
    next_cursor: datetime | None = Field(
        default=None,
        serialization_alias="nextCursor",
    )

    model_config = ConfigDict(populate_by_name=True)


class CursorPaginationParams(BaseModel):
    limit: int = Field(
        default=DEFAULT_CURSOR_PAGE_LIMIT,
        ge=1,
        le=MAX_CURSOR_PAGE_LIMIT,
    )
    before: datetime | None = None


class TaskListResponse(CursorPage[TaskSummary]):
    pass


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "not_ready"]
    service: str


class UploadImageResponse(BaseModel):
    upload_id: str = Field(serialization_alias="uploadId")
    url: str

    model_config = ConfigDict(populate_by_name=True)


class UserModelSummary(BaseModel):
    id: str
    display_name: str
    is_default: bool


class UserModelListResponse(BaseModel):
    models: list[UserModelSummary] = Field(default_factory=list)


class AdminApiKeyCreateRequest(BaseModel):
    label: str = Field(min_length=1)


class AdminApiKeySetActiveRequest(BaseModel):
    is_active: bool = Field(
        validation_alias=AliasChoices("is_active", "isActive"),
        serialization_alias="isActive",
    )

    model_config = ConfigDict(populate_by_name=True)


class AdminApiKeyListItem(BaseModel):
    key_id: str = Field(serialization_alias="keyId")
    label: str
    created_at: datetime = Field(serialization_alias="createdAt")
    is_active: bool = Field(serialization_alias="isActive")

    model_config = ConfigDict(populate_by_name=True)


class AdminApiKeyCreateResponse(BaseModel):
    key_id: str = Field(serialization_alias="keyId")
    token: str
    label: str
    created_at: datetime = Field(serialization_alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class PrivilegedApiKeyCreateRequest(BaseModel):
    scope: Literal["key_manager", "task_viewer", "metrics"]
    label: str = Field(min_length=1)
    allowed_ips: list[str] | None = Field(
        default=None,
        validation_alias=AliasChoices("allowed_ips", "allowedIps"),
        serialization_alias="allowedIps",
    )

    model_config = ConfigDict(populate_by_name=True)


class PrivilegedApiKeyListItem(BaseModel):
    key_id: str = Field(serialization_alias="keyId")
    scope: Literal["key_manager", "task_viewer", "metrics"]
    label: str
    allowed_ips: list[str] | None = Field(
        default=None,
        serialization_alias="allowedIps",
    )
    created_at: datetime = Field(serialization_alias="createdAt")
    is_active: bool = Field(serialization_alias="isActive")

    model_config = ConfigDict(populate_by_name=True)


class PrivilegedApiKeyCreateResponse(PrivilegedApiKeyListItem):
    token: str


def task_type_from_request(value: str) -> TaskType:
    return TaskType(value)
