from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from cubie.auth.api_key_store.constants import USER_KEY_SCOPE
from cubie.auth.api_key_store.normalize import normalize_scope, serialize_row

if TYPE_CHECKING:
    from cubie.auth.api_key_store import ApiKeyStore


_PUBLIC_KEY_FIELDS = """
key_id, label, scope, allowed_ips, created_at, is_active, last_used_at, request_count
"""
_TOKEN_KEY_FIELDS = """
key_id, token, label, scope, allowed_ips, created_at, is_active, last_used_at, request_count
"""


class QueriesMixin:
    def __init__(self, store: ApiKeyStore) -> None:
        self._store = store

    async def list_keys(
        self,
    ) -> list[dict[str, str | bool | int | list[str] | None]]:
        return await self.list_user_keys()

    async def list_user_keys(
        self,
    ) -> list[dict[str, str | bool | int | list[str] | None]]:
        db = self._store.require_db()
        async with db.execute(
            f"""
            SELECT {_PUBLIC_KEY_FIELDS}
            FROM api_keys
            WHERE scope = ?
            ORDER BY created_at DESC, key_id DESC
            """,
            (USER_KEY_SCOPE,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [serialize_row(row) for row in rows]

    async def list_privileged_keys(
        self,
    ) -> list[dict[str, str | bool | int | list[str] | None]]:
        db = self._store.require_db()
        async with db.execute(
            f"""
            SELECT {_PUBLIC_KEY_FIELDS}
            FROM api_keys
            WHERE scope != ?
            ORDER BY created_at DESC, key_id DESC
            """,
            (USER_KEY_SCOPE,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [serialize_row(row) for row in rows]

    async def get_key(
        self,
        key_id: str,
    ) -> dict[str, str | bool | int | list[str] | None] | None:
        return await self.get_user_key(key_id)

    async def get_user_key(
        self,
        key_id: str,
    ) -> dict[str, str | bool | int | list[str] | None] | None:
        db = self._store.require_db()
        async with db.execute(
            f"""
            SELECT {_PUBLIC_KEY_FIELDS}
            FROM api_keys
            WHERE key_id = ? AND scope = ?
            """,
            (key_id, USER_KEY_SCOPE),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return serialize_row(row)

    async def validate_token(
        self,
        token: str | None,
        *,
        required_scope: str | None = None,
    ) -> dict[str, str | bool | int | list[str] | None] | None:
        if token is None:
            return None
        normalized_token = token.strip()
        if not normalized_token:
            return None

        db = self._store.require_db()
        query = f"""
            SELECT {_TOKEN_KEY_FIELDS}
            FROM api_keys
            WHERE is_active = 1
        """
        parameters: tuple[str, ...] = ()
        if required_scope is not None:
            query += " AND scope = ?"
            parameters = (normalize_scope(required_scope),)
        async with db.execute(query, parameters) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            if secrets.compare_digest(normalized_token, str(row["token"])):
                return serialize_row(row)
        return None

    async def get_usage_stats(self) -> dict:
        db = self._store.require_db()
        async with db.execute(
            """
            SELECT
                COUNT(*) AS total_keys,
                COUNT(CASE WHEN is_active = 1 THEN 1 END) AS active_keys,
                COALESCE(SUM(request_count), 0) AS total_requests
            FROM api_keys
            """
        ) as cursor:
            row = await cursor.fetchone()
        return {
            "total_keys": row["total_keys"],
            "active_keys": row["active_keys"],
            "total_requests": row["total_requests"],
        }
