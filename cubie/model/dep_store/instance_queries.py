from __future__ import annotations

from typing import TYPE_CHECKING

from .normalize import (
    normalize_required_text,
    normalize_weight_source,
    row_to_dep_instance,
)

if TYPE_CHECKING:
    from . import DepInstanceStore


class InstanceQueries:
    def __init__(self, store: DepInstanceStore) -> None:
        self._store = store

    async def list_all(self) -> list[dict]:
        db = self._store.require_db()
        async with db.execute(
            "SELECT * FROM dep_instances ORDER BY dep_type, created_at, id"
        ) as cursor:
            rows = await cursor.fetchall()
        return [row_to_dep_instance(row) for row in rows]

    async def list_by_dep_type(self, dep_type: str) -> list[dict]:
        db = self._store.require_db()
        normalized_dep_type = normalize_required_text(dep_type, field="dep_type")
        async with db.execute(
            "SELECT * FROM dep_instances WHERE dep_type = ? ORDER BY created_at, id",
            (normalized_dep_type,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [row_to_dep_instance(row) for row in rows]

    async def get(self, instance_id: str) -> dict | None:
        db = self._store.require_db()
        normalized_instance_id = normalize_required_text(instance_id, field="instance_id")
        async with db.execute(
            "SELECT * FROM dep_instances WHERE id = ?",
            (normalized_instance_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return row_to_dep_instance(row) if row else None

    async def find_duplicate_source(
        self,
        dep_type: str,
        weight_source: str,
        dep_model_path: str,
    ) -> dict | None:
        """Return an existing instance with the same dep_type + weight_source + dep_model_path, or None."""
        db = self._store.require_db()
        normalized_dep_type = normalize_required_text(dep_type, field="dep_type")
        normalized_source = normalize_weight_source(weight_source)
        normalized_path = normalize_required_text(dep_model_path, field="dep_model_path")
        async with db.execute(
            """
            SELECT * FROM dep_instances
            WHERE dep_type = ? AND weight_source = ? AND dep_model_path = ?
            ORDER BY created_at, id
            LIMIT 1
            """,
            (normalized_dep_type, normalized_source, normalized_path),
        ) as cursor:
            row = await cursor.fetchone()
        return row_to_dep_instance(row) if row else None

    async def get_all_resolved_paths(self) -> list[str]:
        db = self._store.require_db()
        async with db.execute(
            """
            SELECT resolved_path FROM dep_instances
            WHERE weight_source != 'local' AND resolved_path IS NOT NULL
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [str(row["resolved_path"]) for row in rows if row["resolved_path"]]

    async def get_all_for_model(self, model_id: str) -> list[dict]:
        db = self._store.require_db()
        normalized_model_id = normalize_required_text(model_id, field="model_id")
        async with db.execute(
            """
            SELECT d.*, m.dep_type AS required_dep_type, m.dep_instance_id
            FROM model_dep_requirements AS m
            JOIN dep_instances AS d ON d.id = m.dep_instance_id
            WHERE m.model_id = ?
            ORDER BY m.dep_type, d.created_at, d.id
            """,
            (normalized_model_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        results: list[dict] = []
        for row in rows:
            item = row_to_dep_instance(row)
            item["dep_type"] = str(row["required_dep_type"] or item["dep_type"])
            item["instance_id"] = str(row["dep_instance_id"] or item["id"])
            results.append(item)
        return results
