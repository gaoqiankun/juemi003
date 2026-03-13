from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    internal_api_key: str = Field(
        default="dev-internal-token",
        alias="INTERNAL_API_KEY",
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
