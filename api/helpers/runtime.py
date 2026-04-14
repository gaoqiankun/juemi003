from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from gen3d.api.helpers.deps import _resolve_dep_paths
from gen3d.api.helpers.gpu_device import _resolve_device_ids
from gen3d.config import ServingConfig
from gen3d.engine.model_registry import ModelRuntime
from gen3d.model.base import ModelProviderConfigurationError
from gen3d.model.hunyuan3d.provider import Hunyuan3DProvider, MockHunyuan3DProvider
from gen3d.model.step1x3d.provider import MockStep1X3DProvider, Step1X3DProvider
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.worker import build_gpu_workers
from gen3d.storage.dep_store import DepInstanceStore, ModelDepRequirementsStore
from gen3d.storage.model_store import ModelStore


def build_provider(
    provider_name: str,
    provider_mode: str,
    model_path: str,
    mock_delay_ms: int = 60,
):
    provider_name = str(provider_name).strip().lower()
    provider_mode = str(provider_mode).strip().lower()
    model_path = str(model_path).strip()

    if provider_name == "trellis2":
        if provider_mode == "mock":
            return MockTrellis2Provider(stage_delay_ms=mock_delay_ms)
        if provider_mode == "real":
            return Trellis2Provider.metadata_only(model_path)
    elif provider_name == "hunyuan3d":
        if provider_mode == "mock":
            return MockHunyuan3DProvider(stage_delay_ms=mock_delay_ms)
        if provider_mode == "real":
            return Hunyuan3DProvider.metadata_only(model_path)
    elif provider_name == "step1x3d":
        if provider_mode == "mock":
            return MockStep1X3DProvider(stage_delay_ms=mock_delay_ms)
        if provider_mode == "real":
            return Step1X3DProvider.metadata_only(model_path)
    else:
        raise ModelProviderConfigurationError(
            f"unsupported MODEL_PROVIDER: {provider_name}"
        )

    raise ModelProviderConfigurationError(
        f"unsupported PROVIDER_MODE: {provider_mode}"
    )

async def _resolve_model_definition_for_runtime(
    model_store: ModelStore,
    normalized_model_name: str,
) -> dict[str, Any]:
    model_definition = await model_store.get_model(normalized_model_name)
    if model_definition is None and normalized_model_name == "trellis":
        # Backward compatibility: legacy tasks that still send "trellis"
        # resolve to the current default model in model_definitions.
        model_definition = await model_store.get_default_model()
    if model_definition is None:
        raise ModelProviderConfigurationError(
            f"model definition not found: {normalized_model_name}"
        )
    return model_definition

async def build_model_runtime(
    model_store: ModelStore,
    config: ServingConfig,
    model_name: str,
    device_ids: tuple[str, ...] | None = None,
    disabled_devices: set[str] | None = None,
    measurement_callback: Callable[[str, str, int], None] | None = None,
) -> ModelRuntime:
    normalized_model_name = str(model_name).strip().lower()
    model_definition = await _resolve_model_definition_for_runtime(
        model_store,
        normalized_model_name,
    )

    provider_name = str(model_definition.get("provider_type") or "").strip().lower()
    if not provider_name:
        raise ModelProviderConfigurationError(
            f"model definition is missing provider_type: {normalized_model_name}"
        )

    download_status = str(model_definition.get("download_status") or "done").strip().lower()
    if download_status != "done" and not config.is_mock_provider:
        raise ModelProviderConfigurationError(
            f"model {normalized_model_name} weights are {download_status}; download must complete first"
        )

    model_path = str(model_definition.get("model_path") or "").strip()
    resolved_path = str(model_definition.get("resolved_path") or "").strip()
    if resolved_path:
        resolved_candidate = Path(resolved_path).expanduser()
        if not resolved_candidate.exists():
            raise ModelProviderConfigurationError(
                f"resolved model path does not exist: {resolved_path}. Download weights first."
            )
        provider_model_path = str(resolved_candidate.resolve())
    else:
        # Backward compatibility for legacy rows: resolved_path may be null.
        provider_model_path = model_path

    if not provider_model_path:
        raise ModelProviderConfigurationError(
            f"model definition is missing model_path: {normalized_model_name}"
        )

    model_id = str(model_definition.get("id") or normalized_model_name).strip()
    dep_instance_store = DepInstanceStore(config.database_path)
    model_dep_store = ModelDepRequirementsStore(config.database_path)
    await dep_instance_store.initialize()
    await model_dep_store.initialize()
    try:
        dep_paths = await _resolve_dep_paths(
            model_id=model_id,
            dep_instance_store=dep_instance_store,
            model_dep_store=model_dep_store,
        )
    finally:
        await dep_instance_store.close()
        await model_dep_store.close()

    provider = await asyncio.to_thread(
        build_provider,
        provider_name=provider_name,
        provider_mode=config.provider_mode,
        model_path=provider_model_path,
        mock_delay_ms=config.mock_gpu_stage_delay_ms,
    )
    resolved_device_ids = tuple(device_ids) if device_ids is not None else _resolve_device_ids(config)
    if not resolved_device_ids:
        resolved_device_ids = ("0",)
    resolved_device_id_set = set(resolved_device_ids)
    scheduler_disabled_devices = {
        device_id
        for device_id in (disabled_devices or set())
        if device_id in resolved_device_id_set
    }
    workers = build_gpu_workers(
        provider=provider,
        provider_mode=config.provider_mode,
        provider_name=provider_name,
        model_path=provider_model_path,
        device_ids=resolved_device_ids,
        dep_paths=dep_paths,
        model_name=normalized_model_name,
        measurement_callback=measurement_callback,
    )
    return ModelRuntime(
        model_name=normalized_model_name,
        provider=provider,
        workers=workers,
        scheduler=GPUSlotScheduler(
            workers,
            disabled_device_ids=scheduler_disabled_devices,
        ),
    )
