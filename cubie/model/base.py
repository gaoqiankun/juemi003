from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class StageProgress:
    stage_name: str
    step: int
    total_steps: int


@dataclass(slots=True)
class GenerationResult:
    mesh: object
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderDependency:
    dep_id: str
    hf_repo_id: str
    description: str


class ModelProviderConfigurationError(RuntimeError):
    pass


class ModelProviderExecutionError(RuntimeError):
    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(message)
        self.stage_name = stage_name


class BaseModelProvider(ABC):
    @classmethod
    def dependencies(cls) -> list[ProviderDependency]:
        return []

    @classmethod
    @abstractmethod
    def from_pretrained(
        cls,
        model_path: str,
        dep_paths: dict[str, str],
    ) -> "BaseModelProvider":
        raise NotImplementedError

    def estimate_weight_vram_mb(self, options: dict[str, Any]) -> int:
        total = self.estimate_vram_mb(batch_size=1, options=options)
        return max(int(total * 0.75), 1)

    def estimate_inference_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        total = self.estimate_vram_mb(batch_size=max(batch_size, 1), options=options)
        return max(total - self.estimate_weight_vram_mb(options=options), 1)

    @abstractmethod
    def estimate_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def stages(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def run_batch(
        self,
        images: list[object],
        options: dict[str, Any],
        progress_cb=None,
        cancel_flags=None,
    ) -> list[GenerationResult]:
        raise NotImplementedError

    @abstractmethod
    def export_glb(
        self,
        result: GenerationResult,
        output_path: str | Path,
        options: dict[str, Any],
    ) -> None:
        raise NotImplementedError
