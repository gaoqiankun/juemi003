from __future__ import annotations

import json
from datetime import datetime

import aiosqlite
from gen3d.task.sequence import RequestSequence, TaskStatus, TaskType, utcnow


def serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def deserialize_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def deserialize_status(value: str) -> TaskStatus:
    normalized = str(value).strip().lower()
    if normalized == "submitted":
        normalized = TaskStatus.QUEUED.value
    return TaskStatus(normalized)


def row_to_sequence(row: aiosqlite.Row) -> RequestSequence:
    return RequestSequence(
        task_id=row["id"],
        task_type=TaskType(row["type"]),
        model=(str(row["model"]).strip() if row["model"] else "trellis") or "trellis",
        input_url=row["input_url"],
        options=json.loads(row["options_json"]),
        callback_url=row["callback_url"],
        idempotency_key=row["idempotency_key"],
        key_id=row["key_id"],
        status=deserialize_status(row["status"]),
        progress=int(row["progress"]),
        current_stage=row["current_stage"] or deserialize_status(row["status"]).value,
        queue_position=row["queue_position"],
        estimated_wait_seconds=row["estimated_wait_seconds"],
        estimated_finish_at=deserialize_datetime(row["estimated_finish_at"]),
        artifacts=json.loads(row["output_artifacts_json"]),
        error_message=row["error_message"],
        failed_stage=row["failed_stage"],
        retry_count=int(row["retry_count"]),
        assigned_worker_id=row["assigned_worker_id"],
        created_at=deserialize_datetime(row["created_at"]) or utcnow(),
        queued_at=deserialize_datetime(row["queued_at"]) or utcnow(),
        started_at=deserialize_datetime(row["started_at"]),
        completed_at=deserialize_datetime(row["completed_at"]),
        updated_at=deserialize_datetime(row["updated_at"]) or utcnow(),
        deleted_at=deserialize_datetime(row["deleted_at"]),
    )
