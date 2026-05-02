from __future__ import annotations

import asyncio
import shutil
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gen3d.artifact import manifest as artifact_manifest
from gen3d.artifact import utils as artifact_utils
from gen3d.artifact.backends.local import ArtifactLocalBackend
from gen3d.artifact.backends.minio import ArtifactMinioBackend
from gen3d.artifact.object_client import (
    Boto3ObjectStorageClient,
    build_boto3_object_storage_client,
)
from gen3d.artifact.types import (
    ArtifactRecord,
    ArtifactStoreConfigurationError,
    ArtifactStoreOperationError,
    ArtifactStream,
    ObjectStorageBodyReader,
    ObjectStorageClient,
    ObjectStorageStreamResult,
)

__all__ = ("ArtifactRecord", "ArtifactStore", "ArtifactStoreConfigurationError", "ArtifactStoreOperationError", "ArtifactStream", "ObjectStorageBodyReader", "ObjectStorageClient", "ObjectStorageStreamResult", "Boto3ObjectStorageClient", "build_boto3_object_storage_client")
_guess_content_type = artifact_utils.guess_content_type


class ArtifactStore:
    def __init__(self, root_dir: Path, *, mode: str = "local", object_store_client: ObjectStorageClient | None = None, object_store_bucket: str | None = None, object_store_prefix: str = "artifacts", object_store_presign_ttl_seconds: int = 3600) -> None:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"local", "minio"}:
            raise ArtifactStoreConfigurationError(f"unsupported artifact store mode: {mode}")
        if normalized_mode == "minio" and object_store_client is None:
            raise ArtifactStoreConfigurationError("minio artifact store requires an object storage client")
        if normalized_mode == "minio" and not object_store_bucket:
            raise ArtifactStoreConfigurationError("minio artifact store requires OBJECT_STORE_BUCKET")
        if object_store_presign_ttl_seconds <= 0:
            raise ArtifactStoreConfigurationError("OBJECT_STORE_PRESIGN_TTL_SECONDS must be greater than 0")
        self._mode = normalized_mode
        self._root_dir = Path(root_dir)
        self._staging_dir = self._root_dir / "_staging"
        self._manifest_dir = self._root_dir / "_manifests"
        self._local_backend = ArtifactLocalBackend(root_dir=self._root_dir)
        self._minio_backend = ArtifactMinioBackend(
            object_store_client=object_store_client,
            object_store_bucket=object_store_bucket,
            object_store_prefix=object_store_prefix.strip("/") or "artifacts",
            object_store_presign_ttl_seconds=object_store_presign_ttl_seconds,
            staging_dir=self._staging_dir,
        ) if normalized_mode == "minio" else None

    @property
    def mode(self) -> str:
        return self._mode

    async def initialize(self) -> None:
        await asyncio.gather(
            asyncio.to_thread(self._root_dir.mkdir, parents=True, exist_ok=True),
            asyncio.to_thread(self._staging_dir.mkdir, parents=True, exist_ok=True),
            asyncio.to_thread(self._manifest_dir.mkdir, parents=True, exist_ok=True),
        )
        if self._minio_backend is not None:
            await self._minio_backend.initialize()

    @asynccontextmanager
    async def create_staging_path(self, task_id: str, file_name: str):
        task_dir = self._staging_dir / task_id
        await asyncio.to_thread(task_dir.mkdir, parents=True, exist_ok=True)
        staging_path = task_dir / file_name
        try:
            yield staging_path
        finally:
            with suppress(FileNotFoundError):
                await asyncio.to_thread(staging_path.unlink)
            with suppress(OSError):
                await asyncio.to_thread(task_dir.rmdir)

    async def publish_artifact(self, *, task_id: str, artifact_type: str, file_name: str, staging_path: Path, content_type: str | None = None) -> dict[str, Any]:
        if not staging_path.exists():
            raise ArtifactStoreOperationError("uploading", f"staged artifact does not exist: {staging_path}")
        created_at = datetime.now(timezone.utc)
        size_bytes = await asyncio.to_thread(lambda: staging_path.stat().st_size)
        resolved_content_type = content_type or artifact_utils.guess_content_type(file_name, artifact_type)
        if self._mode == "local":
            artifact = await self._local_backend.publish_artifact(task_id=task_id, artifact_type=artifact_type, file_name=file_name, staging_path=staging_path, created_at=created_at, size_bytes=size_bytes, content_type=resolved_content_type)
        else:
            artifact = await self.require_minio_backend().publish_artifact(task_id=task_id, artifact_type=artifact_type, file_name=file_name, staging_path=staging_path, created_at=created_at, size_bytes=size_bytes, content_type=resolved_content_type)
        await artifact_manifest.write_manifest(self._manifest_dir, task_id, [artifact])
        return artifact

    async def replace_artifacts(self, task_id: str, artifacts: list[dict[str, Any]]) -> None:
        await artifact_manifest.write_manifest(self._manifest_dir, task_id, artifacts)

    async def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        artifacts = await artifact_manifest.load_manifest(self._manifest_dir, task_id)
        if artifacts is not None:
            if self._mode == "local":
                normalized = artifact_manifest.normalize_local_artifacts(task_id, artifacts)
                if normalized != artifacts:
                    await artifact_manifest.write_manifest(self._manifest_dir, task_id, normalized)
                return normalized
            return artifacts
        if self._mode != "local":
            return []
        scanned = await self._local_backend.list_artifacts(task_id)
        if scanned:
            await artifact_manifest.write_manifest(self._manifest_dir, task_id, scanned)
        return scanned

    async def get_local_artifact_path(self, task_id: str, file_name: str) -> Path | None:
        if self._mode != "local":
            return None
        return await self._local_backend.get_local_artifact_path(task_id, file_name)

    async def prepare_download(self, task_id: str, file_name: str) -> tuple[Path, str | None, bool] | None:
        safe_file_name = artifact_utils.sanitize_file_name(file_name)
        if safe_file_name is None:
            return None
        if self._mode == "local":
            artifact_path = await self._local_backend.get_local_artifact_path(task_id, safe_file_name)
            if artifact_path is None:
                return None
            artifact = await self.find_artifact_record(task_id, safe_file_name)
            artifact_type = str(artifact.get("type") or "file") if artifact is not None else artifact_utils.infer_artifact_type(safe_file_name)
            content_type = str(artifact.get("content_type")) if artifact is not None and artifact.get("content_type") else artifact_utils.guess_content_type(safe_file_name, artifact_type)
            return artifact_path, content_type, False
        artifact = await self.find_artifact_record(task_id, safe_file_name)
        if artifact is None:
            return None
        return await self.require_minio_backend().prepare_download(task_id=task_id, file_name=safe_file_name, artifact=artifact)

    async def open_streaming_download(self, task_id: str, file_name: str) -> ArtifactStream | None:
        safe_file_name = artifact_utils.sanitize_file_name(file_name)
        if safe_file_name is None or self._mode != "minio":
            return None
        artifact = await self.find_artifact_record(task_id, safe_file_name)
        if artifact is None:
            return None
        return await self.require_minio_backend().open_streaming_download(task_id=task_id, file_name=safe_file_name, artifact=artifact)

    async def delete_artifacts(self, task_id: str) -> None:
        if self._mode == "local":
            await self._local_backend.delete_artifacts(task_id)
        else:
            await self.require_minio_backend().delete_artifacts(task_id)
        await artifact_manifest.remove_manifest(self._manifest_dir, task_id)
        staging_dir = self._staging_dir / task_id
        if staging_dir.exists():
            await asyncio.to_thread(shutil.rmtree, staging_dir, True)

    async def find_artifact_record(self, task_id: str, file_name: str) -> dict[str, Any] | None:
        return artifact_manifest.find_artifact_record(await self.list_artifacts(task_id), file_name)

    def require_minio_backend(self) -> ArtifactMinioBackend:
        if self._minio_backend is None:
            raise ArtifactStoreConfigurationError("minio artifact store requires an object storage client")
        return self._minio_backend
