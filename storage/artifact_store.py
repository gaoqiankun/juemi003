from __future__ import annotations

import asyncio
import json
import mimetypes
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactStoreConfigurationError(RuntimeError):
    pass


class ArtifactStoreOperationError(RuntimeError):
    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(message)
        self.stage_name = stage_name


class ObjectStorageClient(Protocol):
    def ensure_bucket_exists(self, bucket: str) -> None: ...

    def upload_file(
        self,
        *,
        bucket: str,
        key: str,
        source_path: Path,
        content_type: str | None = None,
    ) -> None: ...

    def generate_presigned_get_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_in_seconds: int,
    ) -> str: ...


@dataclass(slots=True)
class ArtifactRecord:
    type: str
    url: str
    created_at: str
    size_bytes: int
    backend: str
    content_type: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Boto3ObjectStorageClient:
    def __init__(
        self,
        *,
        endpoint_url: str,
        external_endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        region: str,
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional deps
            raise ArtifactStoreConfigurationError(
                "minio artifact store requires the 'boto3' package"
            ) from exc

        session = boto3.session.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        client_config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )
        self._upload_client = session.client(
            "s3",
            endpoint_url=endpoint_url,
            config=client_config,
        )

        signer_endpoint = external_endpoint_url or endpoint_url
        if signer_endpoint == endpoint_url:
            self._presign_client = self._upload_client
        else:
            self._presign_client = session.client(
                "s3",
                endpoint_url=signer_endpoint,
                config=client_config,
            )

    def ensure_bucket_exists(self, bucket: str) -> None:
        self._upload_client.head_bucket(Bucket=bucket)

    def upload_file(
        self,
        *,
        bucket: str,
        key: str,
        source_path: Path,
        content_type: str | None = None,
    ) -> None:
        extra_args = {"ContentType": content_type} if content_type else None
        self._upload_client.upload_file(
            str(source_path),
            bucket,
            key,
            ExtraArgs=extra_args,
        )

    def generate_presigned_get_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_in_seconds: int,
    ) -> str:
        return self._presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in_seconds,
        )


def build_boto3_object_storage_client(
    *,
    endpoint_url: str,
    external_endpoint_url: str | None,
    access_key: str,
    secret_key: str,
    region: str,
) -> ObjectStorageClient:
    return Boto3ObjectStorageClient(
        endpoint_url=endpoint_url,
        external_endpoint_url=external_endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
    )


class ArtifactStore:
    def __init__(
        self,
        root_dir: Path,
        *,
        mode: str = "local",
        object_store_client: ObjectStorageClient | None = None,
        object_store_bucket: str | None = None,
        object_store_prefix: str = "artifacts",
        object_store_presign_ttl_seconds: int = 3600,
    ) -> None:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"local", "minio"}:
            raise ArtifactStoreConfigurationError(f"unsupported artifact store mode: {mode}")
        if normalized_mode == "minio" and object_store_client is None:
            raise ArtifactStoreConfigurationError(
                "minio artifact store requires an object storage client"
            )
        if normalized_mode == "minio" and not object_store_bucket:
            raise ArtifactStoreConfigurationError(
                "minio artifact store requires OBJECT_STORE_BUCKET"
            )
        if object_store_presign_ttl_seconds <= 0:
            raise ArtifactStoreConfigurationError(
                "OBJECT_STORE_PRESIGN_TTL_SECONDS must be greater than 0"
            )

        self._root_dir = Path(root_dir)
        self._mode = normalized_mode
        self._object_store_client = object_store_client
        self._object_store_bucket = object_store_bucket
        self._object_store_prefix = object_store_prefix.strip("/") or "artifacts"
        self._object_store_presign_ttl_seconds = object_store_presign_ttl_seconds
        self._staging_dir = self._root_dir / "_staging"
        self._manifest_dir = self._root_dir / "_manifests"

    @property
    def mode(self) -> str:
        return self._mode

    async def initialize(self) -> None:
        await asyncio.gather(
            asyncio.to_thread(self._root_dir.mkdir, parents=True, exist_ok=True),
            asyncio.to_thread(self._staging_dir.mkdir, parents=True, exist_ok=True),
            asyncio.to_thread(self._manifest_dir.mkdir, parents=True, exist_ok=True),
        )
        if self._mode != "minio":
            return
        try:
            await asyncio.to_thread(
                self._require_object_store_client().ensure_bucket_exists,
                self._require_object_store_bucket(),
            )
        except Exception as exc:  # pragma: no cover - depends on external runtime
            raise ArtifactStoreConfigurationError(
                f"failed to validate object store bucket "
                f"{self._require_object_store_bucket()!r}: {exc}"
            ) from exc

    @asynccontextmanager
    async def create_staging_path(self, task_id: str, file_name: str):
        task_dir = self._staging_dir / task_id
        await asyncio.to_thread(task_dir.mkdir, parents=True, exist_ok=True)
        staging_path = task_dir / file_name
        try:
            yield staging_path
        finally:
            if staging_path.exists():
                await asyncio.to_thread(staging_path.unlink)
            await asyncio.to_thread(self._prune_empty_dir, task_dir)

    async def publish_artifact(
        self,
        *,
        task_id: str,
        artifact_type: str,
        file_name: str,
        staging_path: Path,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if not staging_path.exists():
            raise ArtifactStoreOperationError(
                "uploading",
                f"staged artifact does not exist: {staging_path}",
            )

        resolved_content_type = content_type or _guess_content_type(file_name, artifact_type)
        created_at = utcnow()
        size_bytes = await asyncio.to_thread(lambda: staging_path.stat().st_size)

        if self._mode == "local":
            artifact = await self._publish_local_artifact(
                task_id=task_id,
                artifact_type=artifact_type,
                file_name=file_name,
                staging_path=staging_path,
                created_at=created_at,
                size_bytes=size_bytes,
                content_type=resolved_content_type,
            )
        else:
            artifact = await self._publish_minio_artifact(
                task_id=task_id,
                artifact_type=artifact_type,
                file_name=file_name,
                staging_path=staging_path,
                created_at=created_at,
                size_bytes=size_bytes,
                content_type=resolved_content_type,
            )

        await self._write_manifest(task_id, [artifact])
        return artifact

    async def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        manifest_path = self._manifest_dir / f"{task_id}.json"
        if manifest_path.exists():
            return await asyncio.to_thread(self._read_manifest, manifest_path)
        if self._mode == "local":
            return await self._scan_local_artifacts(task_id)
        return []

    async def _publish_local_artifact(
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
            url=output_path.resolve().as_uri(),
            created_at=created_at.isoformat(),
            size_bytes=size_bytes,
            backend="local",
            content_type=content_type,
            expires_at=None,
        ).to_dict()

    async def _publish_minio_artifact(
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
        object_key = f"{self._object_store_prefix}/{task_id}/{file_name}"
        client = self._require_object_store_client()
        bucket = self._require_object_store_bucket()
        try:
            await asyncio.to_thread(
                client.upload_file,
                bucket=bucket,
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
                client.generate_presigned_get_url,
                bucket=bucket,
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

    async def _scan_local_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        task_dir = self._root_dir / task_id
        if not task_dir.exists():
            return []

        def build_records() -> list[dict[str, Any]]:
            artifacts: list[dict[str, Any]] = []
            for artifact_path in sorted(task_dir.iterdir()):
                if not artifact_path.is_file():
                    continue
                stat_result = artifact_path.stat()
                artifact_type = "glb" if artifact_path.suffix.lower() == ".glb" else "file"
                artifacts.append(
                    ArtifactRecord(
                        type=artifact_type,
                        url=artifact_path.resolve().as_uri(),
                        created_at=datetime.fromtimestamp(
                            stat_result.st_mtime,
                            tz=timezone.utc,
                        ).isoformat(),
                        size_bytes=stat_result.st_size,
                        backend="local",
                        content_type=_guess_content_type(artifact_path.name, artifact_type),
                        expires_at=None,
                    ).to_dict()
                )
            return artifacts

        artifacts = await asyncio.to_thread(build_records)
        if artifacts:
            await self._write_manifest(task_id, artifacts)
        return artifacts

    async def _write_manifest(
        self,
        task_id: str,
        artifacts: list[dict[str, Any]],
    ) -> None:
        manifest_path = self._manifest_dir / f"{task_id}.json"
        payload = json.dumps(artifacts, ensure_ascii=False, indent=2)
        await asyncio.to_thread(manifest_path.write_text, payload, "utf-8")

    @staticmethod
    def _read_manifest(manifest_path: Path) -> list[dict[str, Any]]:
        return json.loads(manifest_path.read_text("utf-8"))

    @staticmethod
    def _prune_empty_dir(path: Path) -> None:
        try:
            path.rmdir()
        except OSError:
            return

    def _require_object_store_client(self) -> ObjectStorageClient:
        if self._object_store_client is None:
            raise ArtifactStoreConfigurationError(
                "minio artifact store requires an object storage client"
            )
        return self._object_store_client

    def _require_object_store_bucket(self) -> str:
        if not self._object_store_bucket:
            raise ArtifactStoreConfigurationError(
                "minio artifact store requires OBJECT_STORE_BUCKET"
            )
        return self._object_store_bucket


def _guess_content_type(file_name: str, artifact_type: str) -> str | None:
    if artifact_type == "glb" or Path(file_name).suffix.lower() == ".glb":
        return "model/gltf-binary"
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed
