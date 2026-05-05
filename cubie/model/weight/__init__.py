from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import structlog

from .archive import prepare_dep_target_dir, prepare_target_dir
from .deps import DependencyDownloaderMixin
from .downloader import DownloaderMixin
from .storage_scan import StorageScannerMixin


class _ModelStoreProtocol(Protocol):
    async def update_download_progress(
        self,
        model_id: str,
        progress: int,
        speed_bps: int,
    ) -> dict | None:
        ...

    async def update_download_done(
        self,
        model_id: str,
        resolved_path: str,
    ) -> dict | None:
        ...

    async def update_download_error(
        self,
        model_id: str,
        error_message: str,
    ) -> dict | None:
        ...

    async def get_all_resolved_paths(self) -> list[str]:
        ...


class _DepInstanceStoreProtocol(Protocol):
    async def create(
        self,
        instance_id: str,
        dep_type: str,
        hf_repo_id: str,
        display_name: str,
        *,
        weight_source: str = "huggingface",
        dep_model_path: str | None = None,
    ) -> dict:
        ...

    async def get(self, instance_id: str) -> dict | None:
        ...

    async def update_status(self, instance_id: str, status: str) -> dict | None:
        ...

    async def update_done(self, instance_id: str, resolved_path: str) -> dict | None:
        ...

    async def update_error(self, instance_id: str, error: str) -> dict | None:
        ...

    async def get_all_resolved_paths(self) -> list[str]:
        ...


class _ModelDepRequirementsStoreProtocol(Protocol):
    async def assign(self, model_id: str, dep_type: str, dep_instance_id: str) -> None:
        ...


@dataclass(frozen=True)
class ProviderDependency:
    dep_id: str
    hf_repo_id: str
    description: str = ""


def get_provider_deps(provider_type: str) -> list[ProviderDependency]:
    provider_cls = get_provider_class(provider_type)
    return resolve_provider_dependencies(provider_cls)


def cache_key(model_id: str) -> str:
    normalized = str(model_id).strip()
    if not normalized:
        raise ValueError("model_id is required")
    return re.sub(r"[^a-zA-Z0-9_\\-]", "_", normalized)


def normalize_weight_source(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"huggingface", "url", "local"}:
        raise ValueError(
            "weight_source must be one of: huggingface, url, local"
        )
    return normalized


def normalize_weight_source_loose(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "huggingface"
    return normalize_weight_source(normalized)


def get_provider_class(provider_type: str):
    normalized_provider_type = str(provider_type or "").strip().lower()
    if normalized_provider_type == "trellis2":
        from cubie.model.providers.trellis2.provider import Trellis2Provider

        return Trellis2Provider
    if normalized_provider_type == "step1x3d":
        from cubie.model.providers.step1x3d.provider import Step1X3DProvider

        return Step1X3DProvider
    if normalized_provider_type == "hunyuan3d":
        from cubie.model.providers.hunyuan3d.provider import Hunyuan3DProvider

        return Hunyuan3DProvider
    return None


def resolve_provider_dependencies(provider_cls) -> list[ProviderDependency]:
    if provider_cls is None:
        return []
    dependencies_getter = getattr(provider_cls, "dependencies", lambda: [])
    raw_dependencies = dependencies_getter() or []
    normalized_dependencies: list[ProviderDependency] = []
    for item in raw_dependencies:
        dep = normalize_provider_dependency(item)
        if dep is not None:
            normalized_dependencies.append(dep)
    return normalized_dependencies


def normalize_provider_dependency(item: object) -> ProviderDependency | None:
    if isinstance(item, dict):
        raw_dep_id = item.get("dep_id")
        raw_hf_repo_id = item.get("hf_repo_id")
        raw_description = item.get("description")
    else:
        raw_dep_id = getattr(item, "dep_id", None)
        raw_hf_repo_id = getattr(item, "hf_repo_id", None)
        raw_description = getattr(item, "description", "")
    dep_id = str(raw_dep_id or "").strip()
    hf_repo_id = str(raw_hf_repo_id or "").strip()
    if not dep_id or not hf_repo_id:
        return None
    return ProviderDependency(
        dep_id=dep_id,
        hf_repo_id=hf_repo_id,
        description=str(raw_description or "").strip(),
    )

class WeightManager(DownloaderMixin, DependencyDownloaderMixin, StorageScannerMixin):
    _PROGRESS_INTERVAL_SECONDS = 1.0

    def __init__(
        self,
        model_store: _ModelStoreProtocol,
        cache_dir: Path,
        *,
        dep_store: _DepInstanceStoreProtocol | None = None,
        model_dep_requirements_store: _ModelDepRequirementsStoreProtocol | None = None,
    ) -> None:
        self._model_store = model_store
        self._cache_dir = Path(cache_dir).expanduser()
        self._logger = structlog.get_logger(__name__)
        self._dep_store = dep_store
        self._model_dep_requirements_store = model_dep_requirements_store
        self.init_dependency_locks()

    async def resolve_local_path(self, model_path: str) -> str:
        candidate = Path(model_path).expanduser()
        if not candidate.exists():
            raise ValueError(f"local model path does not exist: {model_path}")
        return str(candidate.resolve())

    def prepare_target_dir(self, model_id: str) -> Path:
        return prepare_target_dir(self._cache_dir, model_id)

    def prepare_dep_target_dir(self, instance_id: str) -> Path:
        return prepare_dep_target_dir(self._cache_dir, instance_id)
