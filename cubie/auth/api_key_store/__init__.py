from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from .constants import (
    KEY_MANAGER_SCOPE,
    METRICS_SCOPE,
    PRIVILEGED_KEY_SCOPES,
    TASK_VIEWER_SCOPE,
    USER_KEY_SCOPE,
    VALID_API_KEY_SCOPES,
)
from .migrations import MigrationsMixin
from .mutations import MutationsMixin
from .normalize import (
    deserialize_allowed_ips,
    normalize_allowed_ips,
    normalize_scope,
    serialize_row,
    utcnow_iso,
)
from .queries import QueriesMixin

__all__ = (
    "ApiKeyStore",
    "KEY_MANAGER_SCOPE",
    "METRICS_SCOPE",
    "PRIVILEGED_KEY_SCOPES",
    "TASK_VIEWER_SCOPE",
    "USER_KEY_SCOPE",
    "VALID_API_KEY_SCOPES",
    "deserialize_allowed_ips",
    "normalize_allowed_ips",
    "normalize_scope",
    "serialize_row",
    "utcnow_iso",
)


class ApiKeyStore:
    def __init__(self, database_path: Path) -> None:
        self._db_path = Path(database_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._queries = QueriesMixin(self)
        self._mutations = MutationsMixin(self)
        self._migrations = MigrationsMixin(self)

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._migrations.initialize_schema()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def create_user_key(
        self,
        label: str,
    ) -> dict[str, str | bool | list[str] | None]:
        return await self._mutations.create_user_key(label)

    async def create_privileged_key(
        self,
        *,
        label: str,
        scope: str,
        allowed_ips: list[str] | None = None,
    ) -> dict[str, str | bool | list[str] | None]:
        return await self._mutations.create_privileged_key(
            label=label,
            scope=scope,
            allowed_ips=allowed_ips,
        )

    async def create_key(
        self,
        *,
        label: str,
        scope: str,
        allowed_ips: list[str] | None,
    ) -> dict[str, str | bool | list[str] | None]:
        return await self._mutations.create_key(
            label=label,
            scope=scope,
            allowed_ips=allowed_ips,
        )

    async def list_keys(self) -> list[dict[str, str | bool | int | list[str] | None]]:
        return await self._queries.list_keys()

    async def list_user_keys(
        self,
    ) -> list[dict[str, str | bool | int | list[str] | None]]:
        return await self._queries.list_user_keys()

    async def list_privileged_keys(
        self,
    ) -> list[dict[str, str | bool | int | list[str] | None]]:
        return await self._queries.list_privileged_keys()

    async def set_active(self, key_id: str, is_active: bool) -> bool:
        return await self._mutations.set_active(key_id, is_active)

    async def revoke_privileged_key(self, key_id: str) -> bool:
        return await self._mutations.revoke_privileged_key(key_id)

    async def revoke_user_key(self, key_id: str) -> bool:
        return await self._mutations.revoke_user_key(key_id)

    async def get_key(
        self,
        key_id: str,
    ) -> dict[str, str | bool | int | list[str] | None] | None:
        return await self._queries.get_key(key_id)

    async def get_user_key(
        self,
        key_id: str,
    ) -> dict[str, str | bool | int | list[str] | None] | None:
        return await self._queries.get_user_key(key_id)

    async def validate_token(
        self,
        token: str | None,
        *,
        required_scope: str | None = None,
    ) -> dict[str, str | bool | int | list[str] | None] | None:
        return await self._queries.validate_token(
            token,
            required_scope=required_scope,
        )

    async def record_usage(self, key_id: str) -> None:
        await self._mutations.record_usage(key_id)

    async def get_usage_stats(self) -> dict:
        return await self._queries.get_usage_stats()

    async def ensure_column(self, column_name: str, ddl: str) -> None:
        await self._migrations.ensure_column(column_name, ddl)

    def require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ApiKeyStore.initialize() must be called first")
        return self._db

    @staticmethod
    def serialize_row(
        row: aiosqlite.Row,
    ) -> dict[str, str | bool | int | list[str] | None]:
        return serialize_row(row)
