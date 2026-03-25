from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
from gen3d.engine.sequence import RequestSequence
from gen3d.pagination import CursorPageResult
from gen3d.storage import task_store_analytics as analytics
from gen3d.storage import task_store_mutations as mutations
from gen3d.storage import task_store_queries as queries
from gen3d.storage import task_store_schema as schema
from gen3d.storage.task_store_codec import (
    _deserialize_datetime,
    _deserialize_status,
    _serialize_datetime,
    row_to_sequence,
)
from gen3d.storage.task_store_mutations import TaskIdempotencyConflictError

__all__ = (
    "TaskIdempotencyConflictError",
    "TaskStore",
    "_deserialize_datetime",
    "_deserialize_status",
    "_serialize_datetime",
)


class TaskStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._db = await schema.initialize_task_store(self._database_path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def create_task(self, sequence: RequestSequence) -> None: await mutations.create_task(self._require_db(), self._lock, sequence, row_to_sequence=self._row_to_sequence)
    async def update_task(self, sequence: RequestSequence, *, event: str | None = None, metadata: dict[str, Any] | None = None) -> None: await mutations.update_task(self._require_db(), self._lock, sequence, event=event, metadata=metadata)
    async def append_task_event(self, task_id: str, *, event: str, metadata: dict[str, Any] | None = None, created_at: datetime | None = None) -> None: await mutations.append_task_event(self._require_db(), self._lock, task_id, event=event, metadata=metadata, created_at=created_at)
    async def count_incomplete_tasks(self) -> int: return await queries.count_incomplete_tasks(self._require_db())
    async def count_queued_tasks(self) -> int: return await queries.count_queued_tasks(self._require_db())
    async def count_pending_tasks_by_model(self) -> dict[str, int]: return await queries.count_pending_tasks_by_model(self._require_db())
    async def count_running_tasks_by_model(self) -> dict[str, int]: return await queries.count_running_tasks_by_model(self._require_db())
    async def get_oldest_queued_task_time_by_model(self) -> dict[str, str]: return await queries.get_oldest_queued_task_time_by_model(self._require_db())
    async def claim_next_queued_task(self, worker_id: str) -> RequestSequence | None: return await queries.claim_next_queued_task(self._require_db(), self._lock, worker_id, get_task=self.get_task)
    async def requeue_task(self, task_id: str) -> bool: return await mutations.requeue_task(self._require_db(), self._lock, task_id)
    async def delete_task(self, task_id: str) -> None: await mutations.delete_task(self._require_db(), self._lock, task_id)
    async def get_task(self, task_id: str, *, include_deleted: bool = False) -> RequestSequence | None: return await queries.get_task(self._require_db(), task_id, row_to_sequence=self._row_to_sequence, include_deleted=include_deleted)
    async def list_task_events(self, task_id: str) -> list[dict[str, Any]]: return await queries.list_task_events(self._require_db(), task_id)
    async def get_task_by_idempotency_key(self, idempotency_key: str, *, include_deleted: bool = False) -> RequestSequence | None: return await queries.get_task_by_idempotency_key(self._require_db(), idempotency_key, row_to_sequence=self._row_to_sequence, include_deleted=include_deleted)
    async def list_incomplete_tasks(self) -> list[RequestSequence]: return await queries.list_incomplete_tasks(self._require_db(), row_to_sequence=self._row_to_sequence)
    async def list_tasks(self, *, key_id: str | None, limit: int = 20, before: datetime | None = None) -> CursorPageResult[RequestSequence]: return await queries.list_tasks(self._require_db(), row_to_sequence=self._row_to_sequence, key_id=key_id, limit=limit, before=before)
    async def get_queue_position(self, task_id: str) -> int: return await queries.get_queue_position(self._require_db(), task_id)
    async def soft_delete_task(self, task_id: str, *, deleted_at: datetime | None = None) -> bool: return await mutations.soft_delete_task(self._require_db(), self._lock, task_id, deleted_at=deleted_at)
    async def update_stage_stats(self, *, model: str, stage: str, duration_seconds: float) -> None: await analytics.update_stage_stats(self._require_db(), self._lock, model=model, stage=stage, duration_seconds=duration_seconds)
    async def get_stage_stats(self, model: str) -> dict[str, dict[str, float | int]]: return await analytics.get_stage_stats(self._require_db(), model)
    async def list_pending_cleanups(self, *, limit: int = 20) -> list[str]: return await queries.list_pending_cleanups(self._require_db(), limit=limit)
    async def mark_cleanup_done(self, task_id: str) -> bool: return await mutations.mark_cleanup_done(self._require_db(), self._lock, task_id)
    async def count_tasks_by_status(self) -> dict[str, int]: return await analytics.count_tasks_by_status(self._require_db())
    async def get_recent_tasks(self, limit: int = 10) -> list[dict]: return await analytics.get_recent_tasks(self._require_db(), limit)
    async def get_throughput_stats(self, hours: int = 1) -> dict: return await analytics.get_throughput_stats(self._require_db(), hours)
    async def get_active_task_count(self) -> int: return await analytics.get_active_task_count(self._require_db())

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("TaskStore is not initialized")
        return self._db

    async def _insert_task_event(self, db: aiosqlite.Connection, *, task_id: str, event: str, metadata: dict[str, Any], created_at: datetime | None) -> None:
        await mutations.insert_task_event(db, task_id=task_id, event=event, metadata=metadata, created_at=created_at)

    async def _ensure_task_column(self, column_name: str, definition_sql: str) -> None:
        await schema.ensure_task_column(self._require_db(), column_name, definition_sql)

    def _row_to_sequence(self, row: aiosqlite.Row) -> RequestSequence:
        return row_to_sequence(row)
