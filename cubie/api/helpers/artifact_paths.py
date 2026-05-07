from __future__ import annotations

from pathlib import Path

from cubie.core import ServingConfig


def extract_artifact_filename(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) != 5:
        return None
    if parts[0] != "v1" or parts[1] != "tasks" or parts[3] != "artifacts":
        return None
    return parts[4]


def resolve_dev_local_model_path(config: ServingConfig, filename: str | None) -> Path | None:
    if config.dev_proxy_target is None or filename is None:
        return None
    if Path(filename).name.lower() != "model.glb":
        return None
    if config.dev_local_model_path is None:
        return None
    candidate = config.dev_local_model_path.expanduser()
    if not candidate.is_absolute():
        candidate = (Path(__file__).resolve().parents[1] / candidate).resolve()
    if not candidate.is_file():
        return None
    return candidate
