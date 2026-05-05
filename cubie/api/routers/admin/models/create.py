from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import HTTPException

from cubie.api.helpers.deps import prepare_dep_assignments

from .downloads import (
    cancel_model_download_task,
    run_model_weight_download,
)

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def parse_create_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    model_id = str(payload.get("id") or "").strip()
    provider_type = str(
        payload.get(
            "provider_type",
            payload.get("providerType", payload.get("providerName")),
        )
        or ""
    ).strip()
    display_name = str(payload.get("displayName") or "").strip()
    model_path = str(payload.get("modelPath") or "").strip()
    weight_source = str(
        payload.get("weightSource", payload.get("weight_source")) or ""
    ).strip().lower()
    if not model_id:
        raise HTTPException(status_code=422, detail="id is required")
    if not provider_type:
        raise HTTPException(status_code=422, detail="providerType is required")
    if not display_name:
        raise HTTPException(status_code=422, detail="displayName is required")
    if not model_path:
        raise HTTPException(status_code=422, detail="modelPath is required")
    validate_weight_source(weight_source, model_path)
    return {
        "model_id": model_id,
        "provider_type": provider_type,
        "display_name": display_name,
        "model_path": model_path,
        "weight_source": weight_source,
        "raw_dep_assignments": payload.get("depAssignments", payload.get("dep_assignments")),
    }


def validate_weight_source(weight_source: str, model_path: str) -> None:
    if weight_source not in {"huggingface", "url", "local"}:
        raise HTTPException(
            status_code=422,
            detail="weightSource must be one of: huggingface, url, local",
        )
    if weight_source == "url":
        parsed_url = urlsplit(model_path)
        if parsed_url.scheme not in {"http", "https"}:
            raise HTTPException(
                status_code=422,
                detail="url weightSource requires an http(s) modelPath",
            )
        normalized_url_path = parsed_url.path.strip().lower()
        if not (
            normalized_url_path.endswith(".zip")
            or normalized_url_path.endswith(".tar.gz")
        ):
            raise HTTPException(
                status_code=422,
                detail="url source only supports .zip and .tar.gz archives",
            )
    if weight_source == "local":
        local_candidate = Path(model_path).expanduser()
        if not local_candidate.exists():
            raise HTTPException(
                status_code=422,
                detail=f"local model path does not exist: {model_path}",
            )


async def resolve_local_model(
    container: AppContainer,
    *,
    model: dict,
    model_id: str,
    provider_type: str,
    weight_source: str,
    model_path: str,
    dep_assignments: dict[str, dict],
) -> dict:
    try:
        await container.weight_manager.download(
            model_id=model_id,
            provider_type=provider_type,
            weight_source=weight_source,
            model_path=model_path,
            dep_assignments=dep_assignments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"failed to resolve local model path: {exc}",
        ) from exc
    refreshed_model = await container.model_store.get_model(model_id)
    if refreshed_model is not None:
        model = refreshed_model
    return model


async def handle_create_model(
    container: AppContainer,
    *,
    payload: dict[str, Any],
) -> dict:
    values = parse_create_model_payload(payload)
    model_id = values["model_id"]
    provider_type = values["provider_type"]
    model_path = values["model_path"]
    weight_source = values["weight_source"]
    dep_assignments = await prepare_dep_assignments(
        model_id=model_id,
        provider_type=provider_type,
        raw_dep_assignments=values["raw_dep_assignments"],
        dep_instance_store=container.dep_instance_store,
    )

    try:
        model = await container.model_store.create_model(
            id=model_id,
            provider_type=provider_type,
            display_name=values["display_name"],
            model_path=model_path,
            weight_source=weight_source,
            download_status="downloading",
            download_progress=0,
            download_speed_bps=0,
            resolved_path=None,
            min_vram_mb=payload.get("minVramMb", 24000),
            vram_gb=payload.get("vramGb"),
            weight_vram_mb=payload.get("weightVramMb"),
            inference_vram_mb=payload.get("inferenceVramMb"),
            config=payload.get("config"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if weight_source == "local":
        return await resolve_local_model(
            container,
            model=model,
            model_id=model_id,
            provider_type=provider_type,
            weight_source=weight_source,
            model_path=model_path,
            dep_assignments=dep_assignments,
        )

    existing_task = container.model_download_tasks.get(model_id)
    if existing_task is not None and not existing_task.done():
        await cancel_model_download_task(container, model_id)
    container.model_download_tasks[model_id] = asyncio.create_task(
        run_model_weight_download(
            container,
            model_id=model_id,
            provider_type=provider_type,
            weight_source=weight_source,
            model_path=model_path,
            dep_assignments=dep_assignments,
        ),
        name=f"model-download-{model_id}",
    )
    return model
