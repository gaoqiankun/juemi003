from __future__ import annotations

import asyncio
from typing import Any

from cubie.api.helpers.artifacts import build_artifact_store
from cubie.core.config import ServingConfig
from cubie.model.base import ModelProviderConfigurationError
from cubie.model.providers.trellis2.provider import Trellis2Provider
from cubie.model.store import ModelStore


async def run_real_mode_preflight(config: ServingConfig) -> dict[str, Any]:
    provider_mode = config.provider_mode.strip().lower()
    if provider_mode != "real":
        raise ModelProviderConfigurationError(
            "--check-real-env requires PROVIDER_MODE=real"
        )

    artifact_store = build_artifact_store(config)
    await artifact_store.initialize()

    artifact_report: dict[str, Any] = {
        "mode": artifact_store.mode,
        "artifacts_dir": str(config.artifacts_dir),
    }
    if artifact_store.mode == "minio":
        artifact_report.update(
            {
                "endpoint": config.object_store_endpoint,
                "external_endpoint": config.object_store_external_endpoint,
                "bucket": config.object_store_bucket,
                "prefix": config.object_store_prefix,
                "presign_ttl_seconds": config.object_store_presign_ttl_seconds,
            }
        )

    model_store = ModelStore(config.database_path)
    await model_store.initialize()
    try:
        model_definition = await model_store.get_default_model()
        if model_definition is None:
            model_definitions = await model_store.list_models()
            if not model_definitions:
                raise ModelProviderConfigurationError(
                    "no model definitions found in model_definitions"
                )
            model_definition = model_definitions[0]
    finally:
        await model_store.close()

    provider_name = str(model_definition.get("provider_type") or "").strip().lower()
    model_id = str(model_definition.get("id") or "").strip()
    if provider_name != "trellis2":
        raise ModelProviderConfigurationError(
            f"unsupported MODEL_PROVIDER in model_definitions: {provider_name}"
        )
    model_path = str(model_definition.get("model_path") or "").strip()
    if not model_path:
        raise ModelProviderConfigurationError(
            "default model in model_definitions has empty model_path"
        )

    provider_report = await asyncio.to_thread(
        Trellis2Provider.inspect_runtime,
        model_path,
        load_pipeline=True,
    )
    return {
        "provider_mode": provider_mode,
        "model_id": model_id,
        "provider": provider_report,
        "artifact_store": artifact_report,
    }
