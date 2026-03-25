from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gen3d.storage.artifact_types import ArtifactRecord, ArtifactStoreOperationError
from gen3d.storage.artifact_utils import (
    build_local_proxy_url,
    guess_content_type,
    infer_artifact_type,
    resolve_local_task_dir,
    sanitize_file_name,
)


class ArtifactLocalBackend:
    def __init__(self, *, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    async def publish_artifact(
        self,
        *,
        task_id: str,
        artifact_type: str,
        file_name: str,
        staging_path: Path,
        created_at: datetime,
        size_bytes: int,
        content_type: str | None,
    ) -> dict[str, Any]:
        task_dir = self._root_dir / task_id
        output_path = task_dir / file_name
        try:
            await asyncio.to_thread(task_dir.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(staging_path.replace, output_path)
        except Exception as exc:
            raise ArtifactStoreOperationError(
                "uploading",
                f"failed to finalize local artifact: {exc}",
            ) from exc
        return ArtifactRecord(
            type=artifact_type,
            url=build_local_proxy_url(task_id, file_name),
            created_at=created_at.isoformat(),
            size_bytes=size_bytes,
            backend="local",
            content_type=content_type,
            expires_at=None,
        ).to_dict()

    async def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        task_dir = self._root_dir / task_id
        if not task_dir.exists():
            return []

        def build_records() -> list[dict[str, Any]]:
            artifacts: list[dict[str, Any]] = []
            for artifact_path in sorted(task_dir.iterdir()):
                if not artifact_path.is_file():
                    continue
                stat_result = artifact_path.stat()
                artifact_type = infer_artifact_type(artifact_path.name)
                artifacts.append(
                    ArtifactRecord(
                        type=artifact_type,
                        url=build_local_proxy_url(task_id, artifact_path.name),
                        created_at=datetime.fromtimestamp(
                            stat_result.st_mtime,
                            tz=timezone.utc,
                        ).isoformat(),
                        size_bytes=stat_result.st_size,
                        backend="local",
                        content_type=guess_content_type(artifact_path.name, artifact_type),
                        expires_at=None,
                    ).to_dict()
                )
            return artifacts

        return await asyncio.to_thread(build_records)

    async def get_local_artifact_path(self, task_id: str, file_name: str) -> Path | None:
        task_dir = resolve_local_task_dir(self._root_dir, task_id)
        safe_file_name = sanitize_file_name(file_name)
        if task_dir is None or safe_file_name is None:
            return None

        artifact_path = (task_dir / safe_file_name).resolve()
        try:
            artifact_path.relative_to(task_dir)
        except ValueError:
            return None
        if not artifact_path.is_file():
            return None
        return artifact_path

    async def delete_artifacts(self, task_id: str) -> None:
        task_dir = resolve_local_task_dir(self._root_dir, task_id)
        if task_dir is None or not task_dir.exists():
            return
        try:
            await asyncio.to_thread(shutil.rmtree, task_dir)
        except Exception as exc:
            raise ArtifactStoreOperationError(
                "cleanup",
                f"failed to delete artifacts for task {task_id}: {exc}",
            ) from exc
