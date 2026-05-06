from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from .instance_mutations import InstanceMutations
from .instance_queries import InstanceQueries
from .migrations import (
    ensure_model_dep_requirements_schema,
    ensure_schema,
    initialize_db,
    migrate_legacy_dep_cache,
    table_columns,
    table_exists,
)
from .normalize import (
    normalize_dep_status,
    normalize_download_progress,
    normalize_download_speed_bps,
    normalize_optional_text,
    normalize_required_text,
    normalize_weight_source,
    normalize_weight_source_strict,
    row_to_dep_instance,
)

__all__ = (
    "DepInstanceStore",
    "ModelDepRequirementsStore",
    "ensure_model_dep_requirements_schema",
    "ensure_schema",
    "initialize_db",
    "migrate_legacy_dep_cache",
    "normalize_dep_status",
    "normalize_download_progress",
    "normalize_download_speed_bps",
    "normalize_optional_text",
    "normalize_required_text",
    "normalize_weight_source",
    "normalize_weight_source_strict",
    "row_to_dep_instance",
    "table_columns",
    "table_exists",
)


class _SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._db = await initialize_db(self._db_path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError(f"{self.__class__.__name__}.initialize() must be called first")
        return self._db


class DepInstanceStore(_SQLiteStore):
    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self._queries = InstanceQueries(self)
        self._mutations = InstanceMutations(self)

    async def list_all(self) -> list[dict]:
        return await self._queries.list_all()

    async def list_by_dep_type(self, dep_type: str) -> list[dict]:
        return await self._queries.list_by_dep_type(dep_type)

    async def get(self, instance_id: str) -> dict | None:
        return await self._queries.get(instance_id)

    async def find_duplicate_source(
        self,
        dep_type: str,
        weight_source: str,
        dep_model_path: str,
    ) -> dict | None:
        return await self._queries.find_duplicate_source(
            dep_type,
            weight_source,
            dep_model_path,
        )

    async def create(
        self,
        instance_id: str,
        dep_type: str,
        hf_repo_id: str,
        display_name: str,
        *,
        weight_source: str = "huggingface",
        dep_model_path: str | None = None,
    ) -> dict:
        return await self._mutations.create(
            instance_id,
            dep_type,
            hf_repo_id,
            display_name,
            weight_source=weight_source,
            dep_model_path=dep_model_path,
        )

    async def commit_update(
        self,
        sql: str,
        params: tuple,
        instance_id: str,
    ) -> dict | None:
        return await self._mutations.commit_update(sql, params, instance_id)

    async def update_status(self, instance_id: str, status: str) -> dict | None:
        return await self._mutations.update_status(instance_id, status)

    async def update_progress(self, instance_id: str, progress: int, speed_bps: int) -> dict | None:
        return await self._mutations.update_progress(instance_id, progress, speed_bps)

    async def update_done(self, instance_id: str, resolved_path: str) -> dict | None:
        return await self._mutations.update_done(instance_id, resolved_path)

    async def update_error(self, instance_id: str, error: str) -> dict | None:
        return await self._mutations.update_error(instance_id, error)

    async def get_all_resolved_paths(self) -> list[str]:
        return await self._queries.get_all_resolved_paths()

    async def get_all_for_model(self, model_id: str) -> list[dict]:
        return await self._queries.get_all_for_model(model_id)


class ModelDepRequirementsStore(_SQLiteStore):
    async def assign(self, model_id: str, dep_type: str, dep_instance_id: str) -> None:
        db = self.require_db()
        normalized_model_id = normalize_required_text(model_id, field="model_id")
        normalized_dep_type = normalize_required_text(dep_type, field="dep_type")
        normalized_dep_instance_id = normalize_required_text(
            dep_instance_id,
            field="dep_instance_id",
        )
        async with self._lock:
            await db.execute(
                """
                INSERT OR REPLACE INTO model_dep_requirements (model_id, dep_type, dep_instance_id)
                VALUES (?, ?, ?)
                """,
                (normalized_model_id, normalized_dep_type, normalized_dep_instance_id),
            )
            await db.commit()

    async def get_assignments_for_model(self, model_id: str) -> list[dict]:
        db = self.require_db()
        normalized_model_id = normalize_required_text(model_id, field="model_id")
        async with db.execute(
            """
            SELECT dep_type, dep_instance_id
            FROM model_dep_requirements
            WHERE model_id = ?
            ORDER BY dep_type
            """,
            (normalized_model_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "dep_type": str(row["dep_type"]),
                "dep_instance_id": str(row["dep_instance_id"]),
            }
            for row in rows
        ]
