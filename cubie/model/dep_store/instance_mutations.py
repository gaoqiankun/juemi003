from __future__ import annotations

from typing import TYPE_CHECKING

from .normalize import (
    normalize_dep_status,
    normalize_download_progress,
    normalize_download_speed_bps,
    normalize_optional_text,
    normalize_required_text,
    normalize_weight_source_strict,
)

if TYPE_CHECKING:
    from . import DepInstanceStore


class InstanceMutations:
    def __init__(self, store: DepInstanceStore) -> None:
        self._store = store

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
        db = self._store.require_db()
        normalized_instance_id = normalize_required_text(instance_id, field="instance_id")
        normalized_dep_type = normalize_required_text(dep_type, field="dep_type")
        normalized_hf_repo_id = normalize_required_text(hf_repo_id, field="hf_repo_id")
        normalized_display_name = normalize_required_text(display_name, field="display_name")
        normalized_weight_source = normalize_weight_source_strict(weight_source)
        normalized_dep_model_path = normalize_optional_text(dep_model_path)
        async with self._store._lock:
            try:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO dep_instances
                        (id, dep_type, hf_repo_id, display_name, weight_source, dep_model_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_instance_id,
                        normalized_dep_type,
                        normalized_hf_repo_id,
                        normalized_display_name,
                        normalized_weight_source,
                        normalized_dep_model_path,
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        created = await self._store.get(normalized_instance_id)
        if created is None:
            raise RuntimeError(f"failed to create dep_instances row: {normalized_instance_id}")
        return created

    async def commit_update(
        self,
        sql: str,
        params: tuple,
        instance_id: str,
    ) -> dict | None:
        db = self._store.require_db()
        async with self._store._lock:
            try:
                async with db.execute(sql, params) as cursor:
                    was_updated = cursor.rowcount > 0
                if not was_updated:
                    await db.rollback()
                    return None
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return await self._store.get(instance_id)

    async def update_status(self, instance_id: str, status: str) -> dict | None:
        normalized_instance_id = normalize_required_text(instance_id, field="instance_id")
        normalized_status = normalize_dep_status(status)
        return await self.commit_update(
            "UPDATE dep_instances SET download_status = ? WHERE id = ?",
            (normalized_status, normalized_instance_id),
            normalized_instance_id,
        )

    async def update_progress(self, instance_id: str, progress: int, speed_bps: int) -> dict | None:
        normalized_instance_id = normalize_required_text(instance_id, field="instance_id")
        normalized_progress = normalize_download_progress(progress)
        normalized_speed_bps = normalize_download_speed_bps(speed_bps)
        return await self.commit_update(
            """
            UPDATE dep_instances
            SET
                download_status = 'downloading',
                download_progress = ?,
                download_speed_bps = ?,
                download_error = NULL
            WHERE id = ?
            """,
            (normalized_progress, normalized_speed_bps, normalized_instance_id),
            normalized_instance_id,
        )

    async def update_done(self, instance_id: str, resolved_path: str) -> dict | None:
        normalized_instance_id = normalize_required_text(instance_id, field="instance_id")
        normalized_resolved_path = normalize_optional_text(resolved_path)
        if normalized_resolved_path is None:
            raise ValueError("resolved_path is required when dependency download is done")
        return await self.commit_update(
            """
            UPDATE dep_instances
            SET
                resolved_path = ?,
                download_status = 'done',
                download_progress = 100,
                download_speed_bps = 0,
                download_error = NULL
            WHERE id = ?
            """,
            (normalized_resolved_path, normalized_instance_id),
            normalized_instance_id,
        )

    async def update_error(self, instance_id: str, error: str) -> dict | None:
        normalized_instance_id = normalize_required_text(instance_id, field="instance_id")
        normalized_error = normalize_optional_text(error) or "dependency download failed"
        return await self.commit_update(
            """
            UPDATE dep_instances
            SET
                download_status = 'error',
                download_speed_bps = 0,
                download_error = ?
            WHERE id = ?
            """,
            (normalized_error, normalized_instance_id),
            normalized_instance_id,
        )
