from __future__ import annotations

from pathlib import Path

from cubie.model.base import ModelProviderConfigurationError
from cubie.model.dep_store import DepInstanceStore, ModelDepRequirementsStore


def dep_config_error(
    dep_type: str,
    instance_id: str,
    model_id: str,
    reason: str,
) -> ModelProviderConfigurationError:
    return ModelProviderConfigurationError(
        f"dependency {dep_type} instance {instance_id} for model {model_id} {reason}"
    )


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


def default_dep_assignment(model_id: str, dep_type: str, hf_repo_id: str) -> dict:
    return {
        "new": {
            "instance_id": f"{dep_type}-{model_id}",
            "display_name": dep_type,
            "weight_source": "huggingface",
            "dep_model_path": hf_repo_id,
        }
    }
