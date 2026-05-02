from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException

from cubie.api.helpers.hf import is_hf_repo_id
from cubie.model.base import ModelProviderConfigurationError
from cubie.model.dep_store import DepInstanceStore, ModelDepRequirementsStore
from cubie.model.weight import get_provider_deps


def validation_error(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def dep_config_error(
    dep_type: str,
    instance_id: str,
    model_id: str,
    reason: str,
) -> ModelProviderConfigurationError:
    return ModelProviderConfigurationError(
        f"dependency {dep_type} instance {instance_id} for model {model_id} {reason}"
    )


def provider_dependency_descriptions(provider_type: str) -> dict[str, str]:
    return {dep.dep_id: dep.description for dep in get_provider_deps(provider_type)}


def build_dep_response_rows(
    *,
    provider_type: str,
    dep_rows: list[dict],
) -> list[dict]:
    descriptions = provider_dependency_descriptions(provider_type)
    payload_rows: list[dict] = []
    for dep in dep_rows:
        dep_type = str(dep.get("dep_type") or dep.get("dep_id") or "").strip()
        instance_id = str(dep.get("instance_id") or dep.get("id") or dep.get("dep_id") or "").strip()
        dep_id = dep_type or instance_id
        display_name = str(dep.get("display_name") or instance_id or dep_id).strip()
        payload_rows.append(
            {
                "dep_id": dep_id,
                "dep_type": dep_type or dep_id,
                "instance_id": instance_id or dep_id,
                "id": instance_id or dep_id,
                "display_name": display_name,
                "hf_repo_id": str(dep.get("hf_repo_id") or "").strip(),
                "weight_source": str(dep.get("weight_source") or "huggingface").strip().lower(),
                "dep_model_path": dep.get("dep_model_path"),
                "description": descriptions.get(dep_type, ""),
                "resolved_path": dep.get("resolved_path"),
                "download_status": str(dep.get("download_status") or "pending").strip().lower(),
                "download_progress": int(dep.get("download_progress") or 0),
                "download_speed_bps": int(dep.get("download_speed_bps") or 0),
                "download_error": dep.get("download_error"),
                "revision": None,
            }
        )
    return payload_rows


async def resolve_dep_paths(
    model_id: str,
    dep_instance_store: DepInstanceStore,
    model_dep_store: ModelDepRequirementsStore,
) -> dict[str, str]:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return {}
    assignments = await model_dep_store.get_assignments_for_model(normalized_model_id)
    if not assignments:
        return {}
    dep_paths: dict[str, str] = {}
    for assignment in assignments:
        dep_type = str(assignment.get("dep_type") or "").strip()
        instance_id = str(assignment.get("dep_instance_id") or "").strip()
        if not dep_type or not instance_id:
            raise ModelProviderConfigurationError(
                f"invalid dependency assignment for model {normalized_model_id}"
            )
        dep_row = await dep_instance_store.get(instance_id)
        if dep_row is None:
            raise dep_config_error(
                dep_type, instance_id, normalized_model_id,
                "is missing; please complete dependency download first",
            )
        status = str(dep_row.get("download_status") or "pending").strip().lower()
        resolved_path = str(dep_row.get("resolved_path") or "").strip()
        if status != "done" or not resolved_path:
            raise dep_config_error(
                dep_type, instance_id, normalized_model_id,
                f"is {status}; please complete dependency download first",
            )
        resolved_candidate = Path(resolved_path).expanduser()
        if not resolved_candidate.exists():
            raise dep_config_error(
                dep_type, instance_id, normalized_model_id,
                f"path does not exist: {resolved_path}. please complete dependency download first",
            )
        dep_paths[dep_type] = str(resolved_candidate.resolve())
    return dep_paths


def normalize_new_dep_config(dep_type: str, raw_new: Any) -> dict:
    if not isinstance(raw_new, dict):
        raise validation_error(f"depAssignments.{dep_type}.new must be an object")
    return {
        "instance_id": str(raw_new.get("instance_id", raw_new.get("instanceId")) or "").strip(),
        "display_name": str(raw_new.get("display_name", raw_new.get("displayName")) or "").strip(),
        "weight_source": str(raw_new.get("weight_source", raw_new.get("weightSource")) or "").strip().lower(),
        "dep_model_path": str(raw_new.get("dep_model_path", raw_new.get("depModelPath")) or "").strip(),
    }


def normalize_single_dep_assignment(dep_type: str, raw_assignment: Any) -> dict:
    if not isinstance(raw_assignment, dict):
        raise validation_error(f"depAssignments.{dep_type} must be an object")
    normalized_assignment: dict[str, Any] = {}
    raw_instance_id = raw_assignment.get("instance_id", raw_assignment.get("instanceId"))
    if raw_instance_id is not None:
        instance_id = str(raw_instance_id).strip()
        if not instance_id:
            raise validation_error(f"depAssignments.{dep_type}.instance_id is required")
        normalized_assignment["instance_id"] = instance_id
    if "new" in raw_assignment:
        normalized_assignment["new"] = normalize_new_dep_config(dep_type, raw_assignment.get("new"))
    if "instance_id" in normalized_assignment and "new" in normalized_assignment:
        raise validation_error(f"depAssignments.{dep_type} cannot set both instance_id and new")
    return normalized_assignment


def normalize_dep_assignments_payload(raw_assignments: Any) -> dict[str, dict]:
    if raw_assignments is None:
        return {}
    if not isinstance(raw_assignments, dict):
        raise validation_error("depAssignments must be an object")
    normalized_assignments: dict[str, dict] = {}
    for raw_dep_type, raw_assignment in raw_assignments.items():
        dep_type = str(raw_dep_type or "").strip()
        if not dep_type:
            raise validation_error("depAssignments contains an empty dep_type key")
        normalized_assignments[dep_type] = normalize_single_dep_assignment(dep_type, raw_assignment)
    return normalized_assignments


def default_dep_assignment(model_id: str, dep_type: str, hf_repo_id: str) -> dict:
    return {
        "new": {
            "instance_id": f"{dep_type}-{model_id}",
            "display_name": dep_type,
            "weight_source": "huggingface",
            "dep_model_path": hf_repo_id,
        }
    }


async def validate_existing_dep_assignment(
    dep_type: str,
    instance_id: str,
    dep_instance_store: DepInstanceStore,
) -> dict:
    normalized_instance_id = str(instance_id or "").strip()
    if not normalized_instance_id:
        raise validation_error(f"depAssignments.{dep_type}.instance_id is required")
    existing = await dep_instance_store.get(normalized_instance_id)
    if existing is None:
        raise validation_error(f"dep instance not found: {normalized_instance_id}")
    existing_dep_type = str(existing.get("dep_type") or "").strip()
    if existing_dep_type and existing_dep_type != dep_type:
        raise validation_error(
            f"dep instance {normalized_instance_id} belongs to dep_type {existing_dep_type}, expected {dep_type}",
        )
    return {"instance_id": normalized_instance_id}


def validate_new_dep_model_path(
    dep_type: str,
    hf_repo_id: str,
    weight_source: str,
    dep_model_path: str,
) -> str:
    if weight_source == "local":
        if not dep_model_path:
            raise validation_error(f"dep {dep_type} local source requires dep_model_path")
        if not Path(dep_model_path).expanduser().exists():
            raise validation_error(f"dep {dep_type} local path does not exist: {dep_model_path}")
        return dep_model_path
    if weight_source == "url":
        parsed_url = urlsplit(dep_model_path)
        if parsed_url.scheme not in {"http", "https"}:
            raise validation_error(f"dep {dep_type} url source requires an http(s) dep_model_path")
        url_path = parsed_url.path.strip().lower()
        if not (url_path.endswith(".zip") or url_path.endswith(".tar.gz")):
            raise validation_error(f"dep {dep_type} url source only supports .zip and .tar.gz archives")
        return dep_model_path
    repo_id = dep_model_path or hf_repo_id
    if not is_hf_repo_id(repo_id):
        raise validation_error(f"dep {dep_type} huggingface source requires owner/repo format")
    return repo_id


async def validate_new_dep_assignment(
    dep_type: str,
    hf_repo_id: str,
    new_cfg: dict,
    dep_instance_store: DepInstanceStore,
) -> dict:
    instance_id = str(new_cfg.get("instance_id") or "").strip()
    if not instance_id:
        raise validation_error(f"depAssignments.{dep_type}.new.instance_id is required")
    if await dep_instance_store.get(instance_id) is not None:
        raise validation_error(f"dep instance already exists: {instance_id}")
    display_name = str(new_cfg.get("display_name") or dep_type).strip()
    if not display_name:
        raise validation_error(f"depAssignments.{dep_type}.new.display_name is required")
    weight_source = str(new_cfg.get("weight_source") or "huggingface").strip().lower()
    if weight_source not in {"huggingface", "local", "url"}:
        raise validation_error(
            f"depAssignments.{dep_type}.new.weight_source must be one of: huggingface, local, url",
        )
    dep_model_path = validate_new_dep_model_path(
        dep_type,
        hf_repo_id,
        weight_source,
        str(new_cfg.get("dep_model_path") or "").strip(),
    )
    duplicate = await dep_instance_store.find_duplicate_source(dep_type, weight_source, dep_model_path)
    if duplicate is not None:
        raise validation_error(
            f"dep {dep_type} already has an instance \"{duplicate['display_name']}\" "
            f"with the same source ({weight_source}: {dep_model_path}). "
            f"Use instance_id \"{duplicate['id']}\" instead."
        )
    return {
        "instance_id": instance_id,
        "display_name": display_name,
        "weight_source": weight_source,
        "dep_model_path": dep_model_path,
    }


async def prepare_dep_assignments(
    model_id: str,
    provider_type: str,
    raw_dep_assignments: Any,
    dep_instance_store: DepInstanceStore,
) -> dict[str, dict]:
    dependencies = get_provider_deps(provider_type)
    if not dependencies:
        return {}
    assignments = normalize_dep_assignments_payload(raw_dep_assignments)
    expected_dep_types = {dep.dep_id for dep in dependencies}
    unknown_dep_types = sorted(dep_type for dep_type in assignments if dep_type not in expected_dep_types)
    if unknown_dep_types:
        raise validation_error(f"depAssignments has unknown dep_type: {unknown_dep_types[0]}")
    normalized_assignments: dict[str, dict] = {}
    for dep in dependencies:
        dep_type = dep.dep_id
        assignment = dict(assignments.get(dep_type) or default_dep_assignment(model_id, dep_type, dep.hf_repo_id))
        if "instance_id" in assignment:
            normalized_assignments[dep_type] = await validate_existing_dep_assignment(
                dep_type,
                str(assignment.get("instance_id") or ""),
                dep_instance_store,
            )
            continue
        new_cfg = assignment.get("new")
        if not isinstance(new_cfg, dict):
            raise validation_error(f"depAssignments.{dep_type} must set instance_id or new")
        normalized_assignments[dep_type] = {
            "new": await validate_new_dep_assignment(
                dep_type,
                dep.hf_repo_id,
                new_cfg,
                dep_instance_store,
            )
        }
    return normalized_assignments
