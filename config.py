from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServingConfigurationError(RuntimeError):
    pass


class ServingConfig(BaseSettings):
    service_name: str = "gen3d"
    host: str = "0.0.0.0"
    port: int = 18001
    log_level: str = "info"
    provider_mode: str = Field(default="mock", alias="PROVIDER_MODE")
    model_provider: str = Field(default="trellis2", alias="MODEL_PROVIDER")
    model_path: str = Field(
        default="microsoft/TRELLIS.2-4B",
        alias="MODEL_PATH",
    )
    admin_token: str | None = Field(
        default=None,
        alias="ADMIN_TOKEN",
    )
    database_path: Path = Field(
        default=Path("./data/gen3d.sqlite3"),
        alias="DATABASE_PATH",
    )
    artifact_store_mode: str = Field(default="local", alias="ARTIFACT_STORE_MODE")
    artifacts_dir: Path = Field(
        default=Path("./data/artifacts"),
        alias="ARTIFACTS_DIR",
    )
    uploads_dir: Path = Field(
        default=Path("./data/uploads"),
        alias="UPLOADS_DIR",
    )
    dev_proxy_target: str | None = Field(
        default=None,
        alias="DEV_PROXY_TARGET",
    )
    object_store_endpoint: str | None = Field(
        default=None,
        alias="OBJECT_STORE_ENDPOINT",
    )
    object_store_external_endpoint: str | None = Field(
        default=None,
        alias="OBJECT_STORE_EXTERNAL_ENDPOINT",
    )
    object_store_bucket: str | None = Field(
        default=None,
        alias="OBJECT_STORE_BUCKET",
    )
    object_store_access_key: str | None = Field(
        default=None,
        alias="OBJECT_STORE_ACCESS_KEY",
    )
    object_store_secret_key: str | None = Field(
        default=None,
        alias="OBJECT_STORE_SECRET_KEY",
    )
    object_store_region: str = Field(
        default="us-east-1",
        alias="OBJECT_STORE_REGION",
    )
    object_store_prefix: str = Field(
        default="artifacts",
        alias="OBJECT_STORE_PREFIX",
    )
    object_store_presign_ttl_seconds: int = Field(
        default=3600,
        alias="OBJECT_STORE_PRESIGN_TTL_SECONDS",
    )
    preprocess_delay_ms: int = Field(default=20, alias="PREPROCESS_DELAY_MS")
    preprocess_download_timeout_seconds: float = Field(
        default=15.0,
        alias="PREPROCESS_DOWNLOAD_TIMEOUT_SECONDS",
    )
    preprocess_max_image_bytes: int = Field(
        default=10 * 1024 * 1024,
        alias="PREPROCESS_MAX_IMAGE_BYTES",
    )
    queue_delay_ms: int = Field(default=20, alias="QUEUE_DELAY_MS")
    # Comma-separated GPU device identifiers. One logical worker/slot is created per device.
    gpu_device_ids: tuple[str, ...] = Field(
        default_factory=lambda: ("0",),
        alias="GPU_DEVICE_IDS",
    )
    # Maximum number of tasks allowed to wait in the coordinator queue before new requests
    # are rejected with HTTP 503.
    queue_max_size: int = Field(
        default=20,
        alias="QUEUE_MAX_SIZE",
        ge=0,
    )
    mock_gpu_stage_delay_ms: int = Field(
        default=60,
        alias="MOCK_GPU_STAGE_DELAY_MS",
    )
    mock_export_delay_ms: int = Field(
        default=40,
        alias="MOCK_EXPORT_DELAY_MS",
    )
    webhook_timeout_seconds: float = Field(
        default=2.0,
        alias="WEBHOOK_TIMEOUT_SECONDS",
    )
    # Maximum number of exponential-backoff retries after the initial webhook attempt fails.
    # Retry delays are fixed at 1s, 2s, 4s, ... based on the retry index.
    webhook_max_retries: int = Field(
        default=3,
        alias="WEBHOOK_MAX_RETRIES",
        ge=0,
    )
    # Maximum allowed task age for unfinished tasks before startup recovery marks them failed.
    task_timeout_seconds: int = Field(
        default=3600,
        alias="TASK_TIMEOUT_SECONDS",
        ge=1,
    )
    # Optional comma-separated callback host allowlist.
    # Empty means "allow any callback host".
    allowed_callback_domains: tuple[str, ...] = Field(
        default_factory=tuple,
        alias="ALLOWED_CALLBACK_DOMAINS",
    )
    # Maximum number of in-flight tasks accepted per token at the API layer.
    rate_limit_concurrent: int = Field(
        default=5,
        alias="RATE_LIMIT_CONCURRENT",
        ge=1,
    )
    # Maximum number of POST /v1/tasks requests accepted per token in a rolling hour.
    rate_limit_per_hour: int = Field(
        default=100,
        alias="RATE_LIMIT_PER_HOUR",
        ge=1,
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def provider_mode_normalized(self) -> str:
        return self.provider_mode.strip().lower()

    @property
    def is_mock_provider(self) -> bool:
        return self.provider_mode_normalized == "mock"

    @field_validator("admin_token", mode="before")
    @classmethod
    def _normalize_optional_token(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("dev_proxy_target", mode="before")
    @classmethod
    def _normalize_dev_proxy_target(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().rstrip("/")
        return normalized or None

    @field_validator("dev_proxy_target")
    @classmethod
    def _validate_dev_proxy_target(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("DEV_PROXY_TARGET must be a valid http(s) URL")
        return value

    @field_validator("allowed_callback_domains", mode="before")
    @classmethod
    def _parse_allowed_callback_domains(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            parts = [part.strip().lower().strip(".") for part in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            parts = [str(part).strip().lower().strip(".") for part in value]
        else:
            raise TypeError("ALLOWED_CALLBACK_DOMAINS must be a string or a list")
        return tuple(dict.fromkeys(part for part in parts if part))

    @field_validator("gpu_device_ids", mode="before")
    @classmethod
    def _parse_gpu_device_ids(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ("0",)
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            parts = [str(part).strip() for part in value]
        else:
            raise TypeError("GPU_DEVICE_IDS must be a string or a list")
        normalized = tuple(dict.fromkeys(part for part in parts if part))
        return normalized or ("0",)
