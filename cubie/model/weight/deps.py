from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .archive import (
    detect_archive_format,
    directory_has_entries,
    extract_archive,
    snapshot_has_model_weights,
)
from .downloader import _ProgressTracker, snapshot_download

if TYPE_CHECKING:
    from . import ProviderDependency


class DependencyDownloaderMixin:
    def init_dependency_locks(self) -> None:
        self._dep_locks: dict[str, asyncio.Lock] = {}

    async def download_model_dependencies(
        self,
        model_id: str,
        provider_type: str,
        dep_assignments: dict[str, dict] | None = None,
    ) -> None:
        from . import get_provider_deps, normalize_weight_source_loose

        if self._dep_store is None or self._model_dep_requirements_store is None:
            return
        dependencies = get_provider_deps(provider_type)
        assignments = dep_assignments or {}
        pending_downloads: list[tuple[ProviderDependency, str, str, str | None]] = []

        for dep in dependencies:
            assignment = assignments.get(dep.dep_id) or {}
            dep_type = dep.dep_id
            if "instance_id" in assignment:
                instance_id = str(assignment["instance_id"] or "").strip()
                if not instance_id:
                    raise ValueError(f"dep {dep_type}: instance_id is required")
                instance = await self._dep_store.get(instance_id)
                if instance is None:
                    raise ValueError(f"dep instance not found: {instance_id}")
            else:
                new_cfg = assignment.get("new") or {}
                instance_id = str(new_cfg.get("instance_id") or "").strip()
                if not instance_id:
                    raise ValueError(f"dep {dep_type}: new instance must have instance_id")
                display_name = str(new_cfg.get("display_name") or dep_type).strip() or dep_type
                normalized_source = normalize_weight_source_loose(new_cfg.get("weight_source"))
                dep_model_path = str(new_cfg.get("dep_model_path") or "").strip() or None
                await self._dep_store.create(
                    instance_id,
                    dep_type,
                    dep.hf_repo_id,
                    display_name,
                    weight_source=normalized_source,
                    dep_model_path=dep_model_path,
                )
                pending_downloads.append((dep, instance_id, normalized_source, dep_model_path))
            await self._model_dep_requirements_store.assign(model_id, dep_type, instance_id)

        for dep, instance_id, weight_source, dep_model_path in pending_downloads:
            try:
                await self.download_dep_once(
                    dep,
                    instance_id,
                    weight_source,
                    dep_model_path,
                )
            except Exception as exc:
                raise RuntimeError(f"dep_{dep.dep_id}: {exc}") from exc

    async def download_dep_once(
        self,
        dep: ProviderDependency,
        instance_id: str,
        weight_source: str,
        dep_model_path: str | None,
    ) -> None:
        if self._dep_store is None:
            return
        dep_lock = self._dep_locks.setdefault(instance_id, asyncio.Lock())
        async with dep_lock:
            existing = await self._dep_store.get(instance_id)
            if existing is not None and str(existing.get("download_status") or "").lower() == "done":
                return
            await self._dep_store.update_status(instance_id, "downloading")
            try:
                resolved_path = await self.download_dep(
                    dep,
                    weight_source,
                    dep_model_path,
                    instance_id,
                )
            except Exception as exc:
                await self._dep_store.update_error(instance_id, str(exc))
                raise
            await self._dep_store.update_done(instance_id, resolved_path)

    async def download_dep(
        self,
        dep: ProviderDependency,
        weight_source: str,
        dep_model_path: str | None,
        instance_id: str,
    ) -> str:
        from . import normalize_weight_source_loose

        normalized_source = normalize_weight_source_loose(weight_source)
        normalized_path = str(dep_model_path or "").strip()

        if normalized_source == "local":
            return await self.download_dep_from_local(dep, normalized_path)
        if normalized_source == "url":
            return await self.download_dep_from_url(dep, instance_id, normalized_path)
        repo_id = normalized_path or dep.hf_repo_id
        return await self.download_dep_from_huggingface(dep, repo_id)

    async def download_dep_from_local(self, dep: ProviderDependency, dep_model_path: str) -> str:
        if not dep_model_path:
            raise ValueError(f"dep {dep.dep_id} local source requires dep_model_path")
        return await self.resolve_local_path(dep_model_path)

    async def download_dep_from_url(
        self,
        dep: ProviderDependency,
        instance_id: str,
        source_url: str,
    ) -> str:
        from . import cache_key

        if not source_url:
            raise ValueError(f"dep {dep.dep_id} url source requires dep_model_path")
        archive_format = detect_archive_format(source_url)
        if archive_format is None:
            raise ValueError("url source only supports .zip and .tar.gz archives")

        target_dir = self.prepare_dep_target_dir(instance_id)
        cache_root = self._cache_dir / "deps"
        cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"{cache_key(instance_id)}-",
            dir=str(cache_root),
        ) as tmp_dir:
            archive_path = Path(tmp_dir) / f"dep{archive_format}"
            await self.stream_download(source_url, archive_path, _ProgressTracker())
            await asyncio.to_thread(extract_archive, archive_path, target_dir)
        if not directory_has_entries(target_dir):
            raise ValueError("archive extracted successfully but target directory is empty")
        return str(target_dir.resolve())

    async def download_dep_from_huggingface(self, dep: ProviderDependency, repo_id: str) -> str:
        if snapshot_download is None:
            raise RuntimeError("huggingface_hub is not available")

        def run_download() -> str:
            return snapshot_download(repo_id=repo_id, local_dir=None)

        resolved_path = await asyncio.to_thread(run_download)
        resolved_candidate = Path(str(resolved_path)).expanduser()
        if not directory_has_entries(resolved_candidate):
            raise ValueError(f"downloaded dependency repository is empty: {repo_id}")
        if not snapshot_has_model_weights(resolved_candidate):
            raise ValueError(f"downloaded dependency has no model weights: {repo_id}")
        return str(resolved_candidate.resolve())
