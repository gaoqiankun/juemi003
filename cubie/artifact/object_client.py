from __future__ import annotations

from pathlib import Path

from cubie.artifact.types import (
    ArtifactStoreConfigurationError,
    ObjectStorageClient,
    ObjectStorageStreamResult,
)


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

    def download_file(
        self,
        *,
        bucket: str,
        key: str,
        destination_path: Path,
    ) -> None:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        self._upload_client.download_file(bucket, key, str(destination_path))

    def get_object_stream(
        self,
        *,
        bucket: str,
        key: str,
    ) -> ObjectStorageStreamResult:
        response = self._upload_client.get_object(Bucket=bucket, Key=key)
        return ObjectStorageStreamResult(
            body=response["Body"],
            content_type=response.get("ContentType"),
            content_length=response.get("ContentLength"),
            etag=response.get("ETag"),
        )

    def list_object_keys(
        self,
        *,
        bucket: str,
        prefix: str,
    ) -> list[str]:
        paginator = self._upload_client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item.get("Key")
                if key:
                    keys.append(str(key))
        return keys

    def delete_objects(
        self,
        *,
        bucket: str,
        keys: list[str],
    ) -> None:
        if not keys:
            return
        for index in range(0, len(keys), 1000):
            chunk = keys[index:index + 1000]
            self._upload_client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": key} for key in chunk]},
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
