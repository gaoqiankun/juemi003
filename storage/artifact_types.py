from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


class ArtifactStoreConfigurationError(RuntimeError):
    pass


class ArtifactStoreOperationError(RuntimeError):
    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(message)
        self.stage_name = stage_name


class ObjectStorageBodyReader(Protocol):
    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class ObjectStorageStreamResult:
    body: ObjectStorageBodyReader
    content_type: str | None = None
    content_length: int | None = None
    etag: str | None = None


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

    def download_file(
        self,
        *,
        bucket: str,
        key: str,
        destination_path: Path,
    ) -> None: ...

    def get_object_stream(
        self,
        *,
        bucket: str,
        key: str,
    ) -> ObjectStorageStreamResult: ...

    def list_object_keys(
        self,
        *,
        bucket: str,
        prefix: str,
    ) -> list[str]: ...

    def delete_objects(
        self,
        *,
        bucket: str,
        keys: list[str],
    ) -> None: ...


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


@dataclass(slots=True)
class ArtifactStream:
    file_name: str
    body: ObjectStorageBodyReader
    content_type: str | None
    content_length: int | None = None
    etag: str | None = None
