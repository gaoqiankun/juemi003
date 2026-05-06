from __future__ import annotations

from typing import TYPE_CHECKING

from cubie.auth.api_key_store.constants import USER_KEY_SCOPE

if TYPE_CHECKING:
    from cubie.auth.api_key_store import ApiKeyStore


class MigrationsMixin:
    def __init__(self, store: ApiKeyStore) -> None:
        self._store = store

    async def initialize_schema(self) -> None:
        db = self._store.require_db()
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'user',
                allowed_ips TEXT,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await self.ensure_column(
            "scope",
            f"TEXT NOT NULL DEFAULT '{USER_KEY_SCOPE}'",
        )
        await self.ensure_column("allowed_ips", "TEXT")
        for col_sql in [
            "ALTER TABLE api_keys ADD COLUMN last_used_at TEXT",
            "ALTER TABLE api_keys ADD COLUMN request_count INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                await db.execute(col_sql)
            except Exception:
                pass  # column already exists
        await db.execute(
            "UPDATE api_keys SET scope = ? WHERE scope IS NULL OR TRIM(scope) = ''",
            (USER_KEY_SCOPE,),
        )
        await db.commit()

    async def ensure_column(self, column_name: str, ddl: str) -> None:
        db = self._store.require_db()
        async with db.execute("PRAGMA table_info(api_keys)") as cursor:
            columns = {str(row["name"]) for row in await cursor.fetchall()}
        if column_name in columns:
            return
        await db.execute(f"ALTER TABLE api_keys ADD COLUMN {column_name} {ddl}")
