from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from gen3d.storage.artifact_types import (
    ArtifactRecord,
    ArtifactStoreConfigurationError,
    ArtifactStoreOperationError,
    ArtifactStream,
    ObjectStorageClient,
)
from gen3d.storage.artifact_utils import create_temp_download_path, guess_content_type


class ArtifactMinioBackend:
    def __init__(
        self,
        *,
        object_store_client: ObjectStorageClient,
        object_store_bucket: str,
        object_store_prefix: str,
        object_store_presign_ttl_seconds: int,
        staging_dir: Path,
    ) -> None:
        self._object_store_client = object_store_client
        self._object_store_bucket = object_store_bucket
        self._object_store_prefix = object_store_prefix
        self._object_store_presign_ttl_seconds = object_store_presign_ttl_seconds
        self._staging_dir = staging_dir

    async def initialize(self) -> None:
        try:
            await asyncio.to_thread(
                self._object_store_client.ensure_bucket_exists,
                self._object_store_bucket,
            )
        except Exception as exc:  # pragma: no cover - depends on external runtime
            raise ArtifactStoreConfigurationError(
                f"failed to validate object store bucket "
                f"{self._object_store_bucket!r}: {exc}"
            ) from exc

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
        object_key = self.object_key(task_id, file_name)
        try:
            await asyncio.to_thread(
                self._object_store_client.upload_file,
                bucket=self._object_store_bucket,
                key=object_key,
                source_path=staging_path,
                content_type=content_type,
            )
        except Exception as exc:
            raise ArtifactStoreOperationError(
                "uploading",
                f"failed to upload artifact to object store: {exc}",
            ) from exc

        try:
            url = await asyncio.to_thread(
                self._object_store_client.generate_presigned_get_url,
                bucket=self._object_store_bucket,
                key=object_key,
                expires_in_seconds=self._object_store_presign_ttl_seconds,
            )
        except Exception as exc:
            raise ArtifactStoreOperationError(
                "uploading",
                f"failed to create presigned artifact URL: {exc}",
            ) from exc

        expires_at = created_at + timedelta(seconds=self._object_store_presign_ttl_seconds)
        return ArtifactRecord(
            type=artifact_type,
            url=url,
            created_at=created_at.isoformat(),
            size_bytes=size_bytes,
            backend="minio",
            content_type=content_type,
            expires_at=expires_at.isoformat(),
        ).to_dict()

    async def prepare_download(
        self,
        *,
        task_id: str,
        file_name: str,
        artifact: dict[str, Any],
    ) -> tuple[Path, str | None, bool]:
        download_dir = self._staging_dir / "_downloads" / task_id
        await asyncio.to_thread(download_dir.mkdir, parents=True, exist_ok=True)
        temp_path = await asyncio.to_thread(create_temp_download_path, download_dir, file_name)
        try:
            await asyncio.to_thread(
                self._object_store_client.download_file,
                bucket=self._object_store_bucket,
                key=self.object_key(task_id, file_name),
                destination_path=temp_path,
            )
        except Exception as exc:
            raise ArtifactStoreOperationError(
                "downloading",
                f"failed to download artifact from object store: {exc}",
            ) from exc

        content_type = artifact.get("content_type") or guess_content_type(
            file_name,
            str(artifact.get("type") or "file"),
        )
        return temp_path, content_type, True

    async def open_streaming_download(
        self,
        *,
        task_id: str,
        file_name: str,
        artifact: dict[str, Any],
    ) -> ArtifactStream:
        try:
            stream_result = await asyncio.to_thread(
                self._object_store_client.get_object_stream,
                bucket=self._object_store_bucket,
                key=self.object_key(task_id, file_name),
            )
        except Exception as exc:
            raise ArtifactStoreOperationError(
                "downloading",
                f"failed to stream artifact from object store: {exc}",
            ) from exc

        content_type = stream_result.content_type or artifact.get("content_type") or guess_content_type(
            file_name,
            str(artifact.get("type") or "file"),
        )
        content_length = stream_result.content_length
        if content_length is None:
            size_bytes = artifact.get("size_bytes")
            if isinstance(size_bytes, (int, float)):
                content_length = int(size_bytes)

        return ArtifactStream(
            file_name=file_name,
            body=stream_result.body,
            content_type=content_type,
            content_length=content_length,
            etag=stream_result.etag,
        )

    async def delete_artifacts(self, task_id: str) -> None:
        prefix = f"{self._object_store_prefix}/{task_id}/"
        try:
            keys = await asyncio.to_thread(
                self._object_store_client.list_object_keys,
                bucket=self._object_store_bucket,
                prefix=prefix,
            )
            if keys:
                await asyncio.to_thread(
                    self._object_store_client.delete_objects,
                    bucket=self._object_store_bucket,
                    keys=keys,
                )
        except Exception as exc:
            raise ArtifactStoreOperationError(
                "cleanup",
                f"failed to delete artifacts for task {task_id}: {exc}",
            ) from exc

    def object_key(self, task_id: str, file_name: str) -> str:
        return f"{self._object_store_prefix}/{task_id}/{file_name}"
