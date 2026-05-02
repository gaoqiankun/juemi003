from __future__ import annotations

import mimetypes
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


def build_local_proxy_url(task_id: str, file_name: str) -> str:
    return f"/v1/tasks/{task_id}/artifacts/{quote(file_name, safe='')}"


def sanitize_file_name(file_name: str) -> str | None:
    candidate = Path(file_name)
    if candidate.name != file_name or candidate.name in {"", ".", ".."}:
        return None
    return candidate.name


def artifact_file_name_from_url(value: Any) -> str | None:
    if not value:
        return None
    parsed = urlparse(str(value))
    return Path(parsed.path or str(value)).name or None


def infer_artifact_type(file_name: str) -> str:
    normalized_name = file_name.strip().lower()
    if Path(normalized_name).suffix == ".glb":
        return "glb"
    if normalized_name == "preview.png":
        return "preview"
    if normalized_name == "input.png":
        return "input"
    return "file"


def guess_content_type(file_name: str, artifact_type: str) -> str | None:
    if artifact_type == "glb" or Path(file_name).suffix.lower() == ".glb":
        return "model/gltf-binary"
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed


def resolve_local_task_dir(root_dir: Path, task_id: str) -> Path | None:
    resolved_root = root_dir.resolve()
    task_dir = (resolved_root / task_id).resolve()
    try:
        task_dir.relative_to(resolved_root)
    except ValueError:
        return None
    return task_dir


def create_temp_download_path(download_dir: Path, file_name: str) -> Path:
    suffix = Path(file_name).suffix
    with tempfile.NamedTemporaryFile(
        dir=download_dir,
        prefix=f"{Path(file_name).stem or 'artifact'}.",
        suffix=suffix,
        delete=False,
    ) as handle:
        return Path(handle.name)
