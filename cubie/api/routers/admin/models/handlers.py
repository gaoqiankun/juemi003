from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from cubie.api.helpers.deps import build_dep_response_rows
from cubie.api.helpers.tasks import friendly_model_error_message
from cubie.model.scheduler import SchedulerCapReachedError
from cubie.model.weight import get_provider_deps

from .downloads import cancel_model_download_task

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


async def handle_list_models(
    container: AppContainer,
    *,
    include_pending: bool,
) -> dict:
    extra_statuses = (
        frozenset({"pending"})
        if (not include_pending and container.config.is_mock_provider)
        else frozenset()
    )
    models = await container.model_store.list_models(
        include_pending=include_pending,
        extra_statuses=extra_statuses,
    )
    runtime_states = container.model_registry.runtime_states()
    max_tasks_per_slot = container.model_scheduler.max_tasks_per_slot
    for model in models:
        model_id = str(model["id"]).strip().lower()
        state = str(runtime_states.get(model_id, "not_loaded"))
        model["runtimeState"] = state
        model["runtime_state"] = state
        model["tasks_processed"] = container.model_scheduler.get_tasks_processed(model_id)
        model["maxTasksPerSlot"] = max_tasks_per_slot
        model["max_tasks_per_slot"] = max_tasks_per_slot
        if state == "error":
            error = None
            try:
                error = container.model_registry.get_error(model["id"])
            except Exception:
                error = None
            model["error_message"] = friendly_model_error_message(error)
        else:
            model["error_message"] = None
        if include_pending:
            dep_rows = await container.dep_instance_store.get_all_for_model(model_id)
            model["deps"] = build_dep_response_rows(
                provider_type=str(model.get("provider_type") or ""),
                dep_rows=dep_rows,
            )

    enabled = sum(1 for model in models if model.get("is_enabled"))
    return {
        "models": models,
        "summary": {
            "total": len(models),
            "enabled": enabled,
            "disabled": len(models) - enabled,
        },
    }


async def handle_list_provider_deps(
    container: AppContainer,
    *,
    provider_type: str,
) -> list[dict]:
    dependencies = get_provider_deps(provider_type)
    result: list[dict] = []
    for dep in dependencies:
        instances = await container.dep_instance_store.list_by_dep_type(dep.dep_id)
        result.append(
            {
                "dep_type": dep.dep_id,
                "hf_repo_id": dep.hf_repo_id,
                "description": dep.description,
                "instances": instances,
            }
        )
    return result


async def handle_get_model_deps(
    container: AppContainer,
    *,
    model_id: str,
) -> list[dict]:
    model = await container.model_store.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    dep_rows = await container.dep_instance_store.get_all_for_model(model_id)
    return build_dep_response_rows(
        provider_type=str(model.get("provider_type") or ""),
        dep_rows=dep_rows,
    )


async def handle_load_model(
    container: AppContainer,
    *,
    model_id: str,
) -> dict:
    model = await container.model_store.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    try:
        await container.model_scheduler.request_load(model_id)
    except SchedulerCapReachedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runtime_state = container.model_registry.get_state(model_id)
    return {
        "id": str(model["id"]),
        "runtime_state": runtime_state,
        "runtimeState": runtime_state,
    }


async def handle_unload_model(
    container: AppContainer,
    *,
    model_id: str,
) -> dict:
    model = await container.model_store.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    runtime_state = container.model_registry.get_state(model_id)
    if runtime_state == "not_loaded":
        raise HTTPException(status_code=400, detail="model is not loaded")
    await container.model_registry.unload(model_id)
    runtime_state = container.model_registry.get_state(model_id)
    return {
        "id": str(model["id"]),
        "runtime_state": runtime_state,
        "runtimeState": runtime_state,
    }


async def handle_get_model(
    container: AppContainer,
    *,
    model_id: str,
) -> dict:
    model = await container.model_store.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model


async def handle_update_model(
    container: AppContainer,
    *,
    model_id: str,
    payload: dict,
) -> dict:
    field_map = {
        "isEnabled": "is_enabled",
        "isDefault": "is_default",
        "displayName": "display_name",
        "modelPath": "model_path",
        "minVramMb": "min_vram_mb",
        "vramGb": "vram_gb",
        "weightVramMb": "weight_vram_mb",
        "inferenceVramMb": "inference_vram_mb",
        "config": "config",
    }
    updates = {}
    for camel, snake in field_map.items():
        if camel in payload:
            updates[snake] = payload[camel]
    try:
        model = await container.model_store.update_model(model_id, **updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model


async def handle_delete_model(
    container: AppContainer,
    *,
    model_id: str,
) -> dict:
    model = await container.model_store.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    if str(model.get("download_status") or "").strip().lower() == "done":
        ready_count = await container.model_store.count_ready_models()
        if ready_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="cannot delete the last ready model",
            )
    if str(model.get("download_status") or "").strip().lower() == "downloading":
        await cancel_model_download_task(container, model_id)
    if container.model_registry.get_state(model_id) != "not_loaded":
        await container.model_registry.unload(model_id)
    deleted = await container.model_store.delete_model(model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="model not found")
    return {"ok": True}
