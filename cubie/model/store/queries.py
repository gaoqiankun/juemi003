from __future__ import annotations

from typing import TYPE_CHECKING

from cubie.model.store.normalize import row_to_dict

if TYPE_CHECKING:
    from cubie.model.store import ModelStore


class QueriesMixin:
    def __init__(self, store: ModelStore) -> None:
        self._store = store

    async def list_models(
        self,
        *,
        include_pending: bool = False,
        extra_statuses: frozenset[str] = frozenset(),
    ) -> list[dict]:
        db = self._store.require_db()
        params: tuple[object, ...] = ()
        if include_pending:
            query = "SELECT * FROM model_definitions ORDER BY created_at"
        elif extra_statuses:
            placeholders = ", ".join("?" * (1 + len(extra_statuses)))
            query = (
                "SELECT * FROM model_definitions "
                f"WHERE download_status IN ({placeholders}) "
                "ORDER BY created_at"
            )
            params = tuple(["done", *sorted(extra_statuses)])
        else:
            query = """
            SELECT * FROM model_definitions
            WHERE download_status = 'done'
            ORDER BY created_at
            """
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [row_to_dict(row) for row in rows]

    async def get_model(self, model_id: str) -> dict | None:
        db = self._store.require_db()
        async with db.execute(
            "SELECT * FROM model_definitions WHERE id = ?",
            (model_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return row_to_dict(row) if row else None

    async def get_default_model(self) -> dict | None:
        db = self._store.require_db()
        async with db.execute(
            "SELECT * FROM model_definitions WHERE is_default = 1 LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
        return row_to_dict(row) if row else None

    async def get_enabled_models(
        self,
        *,
        include_pending: bool = False,
        extra_statuses: frozenset[str] = frozenset(),
    ) -> list[dict]:
        db = self._store.require_db()
        params: tuple[object, ...] = ()
        if include_pending:
            query = (
                "SELECT * FROM model_definitions "
                "WHERE is_enabled = 1 ORDER BY created_at"
            )
        elif extra_statuses:
            placeholders = ", ".join("?" * (1 + len(extra_statuses)))
            query = (
                "SELECT * FROM model_definitions "
                "WHERE is_enabled = 1 "
                f"AND download_status IN ({placeholders}) "
                "ORDER BY created_at"
            )
            params = tuple(["done", *sorted(extra_statuses)])
        else:
            query = """
            SELECT * FROM model_definitions
            WHERE is_enabled = 1 AND download_status = 'done'
            ORDER BY created_at
            """
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [row_to_dict(row) for row in rows]

    async def count_ready_models(self) -> int:
        db = self._store.require_db()
        async with db.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM model_definitions
            WHERE download_status = 'done'
            """
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"])

    async def get_all_resolved_paths(self) -> list[str]:
        db = self._store.require_db()
        async with db.execute(
            """
            SELECT resolved_path FROM model_definitions
            WHERE weight_source != 'local' AND resolved_path IS NOT NULL
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [str(row["resolved_path"]) for row in rows if row["resolved_path"]]
