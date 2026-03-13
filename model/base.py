from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True)
class StageProgress:
    stage_name: str
    step: int
    total_steps: int


@dataclass(slots=True)
class GenerationResult:
    mesh: object
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelProviderConfigurationError(RuntimeError):
    pass


class ModelProviderExecutionError(RuntimeError):
    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(message)
        self.stage_name = stage_name


class BaseModelProvider(Protocol):
    @classmethod
    def from_pretrained(cls, model_path: str) -> "BaseModelProvider": ...

    def estimate_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int: ...

    @property
    def stages(self) -> list[dict[str, Any]]: ...

    async def run_batch(
        self,
        images: list[object],
        options: dict[str, Any],
        progress_cb=None,
        cancel_flags=None,
    ) -> list[GenerationResult]: ...

    def export_glb(
        self,
        result: GenerationResult,
        output_path: str | Path,
        options: dict[str, Any],
    ) -> None: ...
