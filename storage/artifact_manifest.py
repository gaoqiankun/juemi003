from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from gen3d.storage.artifact_utils import (
    artifact_file_name_from_url,
    build_local_proxy_url,
)


async def load_manifest(
    manifest_dir: Path,
    task_id: str,
) -> list[dict[str, Any]] | None:
    manifest_path = manifest_dir / f"{task_id}.json"
    if not manifest_path.exists():
        return None
    return await asyncio.to_thread(_read_manifest, manifest_path)


async def write_manifest(
    manifest_dir: Path,
    task_id: str,
    artifacts: list[dict[str, Any]],
) -> None:
    manifest_path = manifest_dir / f"{task_id}.json"
    payload = json.dumps(artifacts, ensure_ascii=False, indent=2)
    temp_manifest_path = await asyncio.to_thread(
        _write_manifest_temp_file,
        manifest_path,
        payload,
    )
    await asyncio.to_thread(temp_manifest_path.replace, manifest_path)


async def remove_manifest(manifest_dir: Path, task_id: str) -> None:
    manifest_path = manifest_dir / f"{task_id}.json"
    await asyncio.to_thread(_delete_if_exists, manifest_path)


def normalize_local_artifacts(
    task_id: str,
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact.get("backend") != "local":
            normalized.append(artifact)
            continue
        file_name = artifact_file_name_from_url(artifact.get("url"))
        if file_name is None:
            normalized.append(artifact)
            continue
        updated = dict(artifact)
        updated["url"] = build_local_proxy_url(task_id, file_name)
        normalized.append(updated)
    return normalized


def find_artifact_record(
    artifacts: list[dict[str, Any]],
    file_name: str,
) -> dict[str, Any] | None:
    for artifact in artifacts:
        if artifact_file_name_from_url(artifact.get("url")) == file_name:
            return artifact
    return None


def _read_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    return json.loads(manifest_path.read_text("utf-8"))


def _write_manifest_temp_file(manifest_path: Path, payload: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=manifest_path.parent,
        prefix=f"{manifest_path.stem}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        return Path(handle.name)


def _delete_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
