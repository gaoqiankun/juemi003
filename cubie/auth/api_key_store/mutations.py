from __future__ import annotations

import json
import secrets
import uuid
from typing import TYPE_CHECKING

import aiosqlite

from cubie.auth.api_key_store.constants import PRIVILEGED_KEY_SCOPES, USER_KEY_SCOPE
from cubie.auth.api_key_store.normalize import (
    normalize_allowed_ips,
    normalize_scope,
    utcnow_iso,
)

if TYPE_CHECKING:
    from cubie.auth.api_key_store import ApiKeyStore


class MutationsMixin:
    def __init__(self, store: ApiKeyStore) -> None:
        self._store = store

    async def create_user_key(
        self,
        label: str,
    ) -> dict[str, str | bool | list[str] | None]:
        return await self.create_key(
            label=label,
            scope=USER_KEY_SCOPE,
            allowed_ips=None,
        )

    async def create_privileged_key(
        self,
        *,
        label: str,
        scope: str,
        allowed_ips: list[str] | None = None,
    ) -> dict[str, str | bool | list[str] | None]:
        normalized_scope = normalize_scope(scope)
        if normalized_scope not in PRIVILEGED_KEY_SCOPES:
            raise ValueError("scope must be one of: key_manager, task_viewer, metrics")
        return await self.create_key(
            label=label,
            scope=normalized_scope,
            allowed_ips=allowed_ips,
        )

    async def create_key(
        self,
        *,
        label: str,
        scope: str,
        allowed_ips: list[str] | None,
    ) -> dict[str, str | bool | list[str] | None]:
        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("label is required")
        normalized_scope = normalize_scope(scope)
        normalized_allowed_ips = normalize_allowed_ips(allowed_ips)

        db = self._store.require_db()
        async with self._store._lock:
            for _ in range(5):
                created_at = utcnow_iso()
                payload = {
                    "key_id": uuid.uuid4().hex,
                    "token": secrets.token_urlsafe(32),
                    "label": normalized_label,
                    "scope": normalized_scope,
                    "allowed_ips": normalized_allowed_ips,
                    "created_at": created_at,
                    "is_active": True,
                }
                try:
                    await db.execute(
                        """
                        INSERT INTO api_keys (
                            key_id,
                            token,
                            label,
                            scope,
                            allowed_ips,
                            created_at,
                            is_active
                        ) VALUES (?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            payload["key_id"],
                            payload["token"],
                            payload["label"],
                            payload["scope"],
                            (
                                json.dumps(payload["allowed_ips"])
                                if payload["allowed_ips"] is not None
                                else None
                            ),
                            payload["created_at"],
                        ),
                    )
                except aiosqlite.IntegrityError:
                    continue
                await db.commit()
                return payload
        raise RuntimeError("failed to generate a unique API key")

    async def set_active(self, key_id: str, is_active: bool) -> bool:
        db = self._store.require_db()
        async with self._store._lock:
            async with db.execute(
                """
                UPDATE api_keys
                SET is_active = ?
                WHERE key_id = ? AND scope = ?
                """,
                (1 if is_active else 0, key_id, USER_KEY_SCOPE),
            ) as cursor:
                was_updated = cursor.rowcount > 0
            await db.commit()
            return was_updated

    async def revoke_privileged_key(self, key_id: str) -> bool:
        db = self._store.require_db()
        async with self._store._lock:
            async with db.execute(
                "DELETE FROM api_keys WHERE key_id = ? AND scope != ?",
                (key_id, USER_KEY_SCOPE),
            ) as cursor:
                was_deleted = cursor.rowcount > 0
            await db.commit()
            return was_deleted

    async def revoke_user_key(self, key_id: str) -> bool:
        db = self._store.require_db()
        async with self._store._lock:
            async with db.execute(
                "DELETE FROM api_keys WHERE key_id = ? AND scope = ?",
                (key_id, USER_KEY_SCOPE),
            ) as cursor:
                was_deleted = cursor.rowcount > 0
            await db.commit()
            return was_deleted

    async def record_usage(self, key_id: str) -> None:
        db = self._store.require_db()
        async with self._store._lock:
            await db.execute(
                """
                UPDATE api_keys
                SET request_count = request_count + 1, last_used_at = ?
                WHERE key_id = ?
                """,
                (utcnow_iso(), key_id),
            )
            await db.commit()
