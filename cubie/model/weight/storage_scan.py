from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from .archive import compute_dir_size


class StorageScannerMixin:
    async def get_storage_stats(self) -> dict:
        disk = shutil.disk_usage(self._cache_dir if self._cache_dir.exists() else Path("/"))
        model_paths = await self._model_store.get_all_resolved_paths()
        dep_paths: list[str] = []
        if self._dep_store is not None:
            dep_paths = await self._dep_store.get_all_resolved_paths()
        resolved = {str(Path(p).resolve()) for p in model_paths + dep_paths}

        scan_dirs: list[Path] = []
        if self._cache_dir.exists():
            for d in self._cache_dir.iterdir():
                if d.is_dir() and d.name != "deps":
                    scan_dirs.append(d)
        deps_dir = self._cache_dir / "deps"
        if deps_dir.exists():
            for d in deps_dir.iterdir():
                if d.is_dir():
                    scan_dirs.append(d)

        cache_bytes = 0
        orphan_bytes = 0
        orphan_count = 0
        for d in scan_dirs:
            size = await asyncio.to_thread(compute_dir_size, d)
            cache_bytes += size
            if str(d.resolve()) not in resolved:
                orphan_bytes += size
                orphan_count += 1

        return {
            "disk_free_bytes": disk.free,
            "disk_total_bytes": disk.total,
            "cache_bytes": cache_bytes,
            "orphan_bytes": orphan_bytes,
            "orphan_count": orphan_count,
        }

    async def list_orphans(self) -> list[dict]:
        model_paths = await self._model_store.get_all_resolved_paths()
        dep_paths: list[str] = []
        if self._dep_store is not None:
            dep_paths = await self._dep_store.get_all_resolved_paths()
        resolved = {str(Path(p).resolve()) for p in model_paths + dep_paths}

        orphan_dirs: list[Path] = []
        if self._cache_dir.exists():
            for d in self._cache_dir.iterdir():
                if d.is_dir() and d.name != "deps" and str(d.resolve()) not in resolved:
                    orphan_dirs.append(d)
        deps_dir = self._cache_dir / "deps"
        if deps_dir.exists():
            for d in deps_dir.iterdir():
                if d.is_dir() and str(d.resolve()) not in resolved:
                    orphan_dirs.append(d)

        result = []
        for d in sorted(orphan_dirs):
            size = await asyncio.to_thread(compute_dir_size, d)
            result.append({"path": str(d), "size_bytes": size})
        return result

    async def get_storage_breakdown(self) -> dict:
        seen: set[str] = set()
        entries = []

        await append_model_storage_entries(self._model_store, seen, entries)
        if self._dep_store is not None:
            await append_dep_storage_entries(self._dep_store, seen, entries)
        await append_residual_storage_entries(self._cache_dir, seen, entries)

        entries.sort(key=lambda x: x["size_bytes"], reverse=True)
        return {"entries": entries}

    async def clean_orphans(self) -> dict:
        model_paths = await self._model_store.get_all_resolved_paths()
        dep_paths: list[str] = []
        if self._dep_store is not None:
            dep_paths = await self._dep_store.get_all_resolved_paths()
        resolved = {str(Path(p).resolve()) for p in model_paths + dep_paths}

        orphan_dirs: list[Path] = []
        if self._cache_dir.exists():
            for d in self._cache_dir.iterdir():
                if d.is_dir() and d.name != "deps" and str(d.resolve()) not in resolved:
                    orphan_dirs.append(d)
        deps_dir = self._cache_dir / "deps"
        if deps_dir.exists():
            for d in deps_dir.iterdir():
                if d.is_dir() and str(d.resolve()) not in resolved:
                    orphan_dirs.append(d)

        freed_bytes = 0
        count = 0
        for d in orphan_dirs:
            size = await asyncio.to_thread(compute_dir_size, d)
            freed_bytes += size
            await asyncio.to_thread(shutil.rmtree, str(d), True)
            count += 1
            self._logger.info("orphan_cleaned", path=str(d), size_bytes=size)

        return {"freed_bytes": freed_bytes, "count": count}


async def append_model_storage_entries(model_store, seen: set[str], entries: list) -> None:
    # Known model paths (including local weight_source outside cache_dir)
    for m in await model_store.list_models(include_pending=False):
        resolved = m.get("resolved_path") or ""
        if not resolved:
            continue
        p = Path(resolved)
        key = str(p.resolve())
        if key in seen or not p.exists():
            continue
        seen.add(key)
        size = await asyncio.to_thread(compute_dir_size, p)
        entries.append(
            {
                "path": resolved,
                "size_bytes": size,
                "label": m.get("display_name", ""),
                "kind": "model",
            }
        )


async def append_dep_storage_entries(dep_store, seen: set[str], entries: list) -> None:
    # Known dep paths
    for d in await dep_store.list_all():
        resolved = d.get("resolved_path") or ""
        if not resolved:
            continue
        p = Path(resolved)
        key = str(p.resolve())
        if key in seen or not p.exists():
            continue
        seen.add(key)
        size = await asyncio.to_thread(compute_dir_size, p)
        entries.append(
            {
                "path": resolved,
                "size_bytes": size,
                "label": d.get("display_name", ""),
                "kind": "dep",
            }
        )


async def append_residual_storage_entries(
    cache_dir: Path,
    seen: set[str],
    entries: list,
) -> None:
    # Residual dirs in cache_dir not matched above
    scan_dirs: list[Path] = []
    if cache_dir.exists():
        for d in cache_dir.iterdir():
            if d.is_dir() and d.name != "deps":
                scan_dirs.append(d)
    deps_dir = cache_dir / "deps"
    if deps_dir.exists():
        for d in deps_dir.iterdir():
            if d.is_dir():
                scan_dirs.append(d)
    for d in scan_dirs:
        if str(d.resolve()) in seen:
            continue
        size = await asyncio.to_thread(compute_dir_size, d)
        entries.append(
            {"path": str(d), "size_bytes": size, "label": None, "kind": "residual"}
        )
