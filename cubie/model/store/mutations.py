from __future__ import annotations

import json
from typing import TYPE_CHECKING

import aiosqlite

from cubie.model.store.normalize import (
    normalize_download_progress,
    normalize_download_speed_bps,
    normalize_download_status,
    normalize_optional_text,
    normalize_optional_vram_mb,
    normalize_vram_gb,
    normalize_weight_source,
    utcnow_iso,
)

if TYPE_CHECKING:
    from cubie.model.store import ModelStore


_UPDATABLE_FIELDS = frozenset(
    {
        "is_enabled",
        "is_default",
        "display_name",
        "model_path",
        "min_vram_mb",
        "vram_gb",
        "weight_vram_mb",
        "inference_vram_mb",
        "config",
    }
)


class MutationsMixin:
    def __init__(self, store: ModelStore) -> None:
        self._store = store

    async def create_model(
        self,
        *,
        id: str,
        provider_type: str,
        display_name: str,
        model_path: str,
        weight_source: str = "huggingface",
        download_status: str = "done",
        download_progress: int = 100,
        download_speed_bps: int = 0,
        download_error: str | None = None,
        resolved_path: str | None = None,
        min_vram_mb: int = 24000,
        vram_gb: float | None = None,
        weight_vram_mb: int | None = None,
        inference_vram_mb: int | None = None,
        config: dict | None = None,
    ) -> dict:
        db = self._store.require_db()
        now = utcnow_iso()
        config_json = json.dumps(config or {})
        normalized_vram_gb = normalize_vram_gb(vram_gb)
        normalized_weight_vram_mb = normalize_optional_vram_mb(weight_vram_mb)
        normalized_inference_vram_mb = normalize_optional_vram_mb(inference_vram_mb)
        normalized_weight_source = normalize_weight_source(weight_source)
        normalized_download_status = normalize_download_status(download_status)
        normalized_download_progress = normalize_download_progress(download_progress)
        normalized_download_speed_bps = normalize_download_speed_bps(download_speed_bps)
        normalized_download_error = normalize_optional_text(download_error)
        normalized_resolved_path = normalize_optional_text(resolved_path)
        async with self._store._lock:
            try:
                await db.execute(
                    """
                    INSERT INTO model_definitions
                        (id, provider_type, display_name, model_path,
                         weight_source, download_status, download_progress,
                         download_speed_bps, download_error, resolved_path,
                         is_enabled, is_default, min_vram_mb, vram_gb,
                         weight_vram_mb, inference_vram_mb, config_json,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        id,
                        provider_type,
                        display_name,
                        model_path,
                        normalized_weight_source,
                        normalized_download_status,
                        normalized_download_progress,
                        normalized_download_speed_bps,
                        normalized_download_error,
                        normalized_resolved_path,
                        min_vram_mb,
                        normalized_vram_gb,
                        normalized_weight_vram_mb,
                        normalized_inference_vram_mb,
                        config_json,
                        now,
                        now,
                    ),
                )
            except aiosqlite.IntegrityError:
                raise ValueError(f"model with id '{id}' already exists")
            await db.commit()
        return await self._store.get_model(id)  # type: ignore[return-value]

    async def update_model(self, model_id: str, **updates: object) -> dict | None:
        invalid = set(updates) - _UPDATABLE_FIELDS
        if invalid:
            raise ValueError(f"invalid update fields: {invalid}")
        if not updates:
            return await self._store.get_model(model_id)

        db = self._store.require_db()
        async with self._store._lock:
            if updates.get("is_default") is True:
                await db.execute(
                    "UPDATE model_definitions SET is_default = 0 WHERE is_default = 1"
                )

            set_clauses: list[str] = []
            params: list[object] = []
            for key, value in updates.items():
                if key == "config":
                    set_clauses.append("config_json = ?")
                    params.append(json.dumps(value or {}))
                elif key == "vram_gb":
                    set_clauses.append("vram_gb = ?")
                    params.append(normalize_vram_gb(value))
                elif key in {"weight_vram_mb", "inference_vram_mb"}:
                    set_clauses.append(f"{key} = ?")
                    params.append(normalize_optional_vram_mb(value))
                elif key in ("is_enabled", "is_default"):
                    set_clauses.append(f"{key} = ?")
                    params.append(1 if value else 0)
                else:
                    set_clauses.append(f"{key} = ?")
                    params.append(value)

            set_clauses.append("updated_at = ?")
            params.append(utcnow_iso())
            params.append(model_id)

            async with db.execute(
                f"UPDATE model_definitions SET {', '.join(set_clauses)} WHERE id = ?",
                params,
            ) as cursor:
                was_updated = cursor.rowcount > 0
            if not was_updated:
                await db.rollback()
                return None
            await db.commit()
        return await self._store.get_model(model_id)

    async def delete_model(self, model_id: str) -> bool:
        db = self._store.require_db()
        async with self._store._lock:
            async with db.execute(
                "DELETE FROM model_definitions WHERE id = ?",
                (model_id,),
            ) as cursor:
                was_deleted = cursor.rowcount > 0
            await db.commit()
            return was_deleted

    async def update_download_progress(
        self,
        model_id: str,
        progress: int,
        speed_bps: int,
    ) -> dict | None:
        db = self._store.require_db()
        normalized_progress = normalize_download_progress(progress)
        normalized_speed_bps = normalize_download_speed_bps(speed_bps)
        async with self._store._lock:
            async with db.execute(
                """
                UPDATE model_definitions
                SET
                    download_status = 'downloading',
                    download_progress = ?,
                    download_speed_bps = ?,
                    download_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_progress,
                    normalized_speed_bps,
                    utcnow_iso(),
                    model_id,
                ),
            ) as cursor:
                was_updated = cursor.rowcount > 0
            if not was_updated:
                await db.rollback()
                return None
            await db.commit()
        return await self._store.get_model(model_id)

    async def update_download_done(
        self,
        model_id: str,
        resolved_path: str,
    ) -> dict | None:
        db = self._store.require_db()
        normalized_resolved_path = normalize_optional_text(resolved_path)
        if normalized_resolved_path is None:
            raise ValueError("resolved_path is required when marking download as done")
        async with self._store._lock:
            async with db.execute(
                """
                UPDATE model_definitions
                SET
                    download_status = 'done',
                    download_progress = 100,
                    download_speed_bps = 0,
                    download_error = NULL,
                    resolved_path = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_resolved_path,
                    utcnow_iso(),
                    model_id,
                ),
            ) as cursor:
                was_updated = cursor.rowcount > 0
            if not was_updated:
                await db.rollback()
                return None
            await db.commit()
        return await self._store.get_model(model_id)

    async def update_download_error(
        self,
        model_id: str,
        error_message: str,
    ) -> dict | None:
        db = self._store.require_db()
        normalized_error = normalize_optional_text(error_message) or "download failed"
        async with self._store._lock:
            async with db.execute(
                """
                UPDATE model_definitions
                SET
                    download_status = 'error',
                    download_speed_bps = 0,
                    download_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_error,
                    utcnow_iso(),
                    model_id,
                ),
            ) as cursor:
                was_updated = cursor.rowcount > 0
            if not was_updated:
                await db.rollback()
                return None
            await db.commit()
        return await self._store.get_model(model_id)
