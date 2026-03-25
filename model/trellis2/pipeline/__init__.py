from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "Trellis2ImageTo3DPipeline",
    "from_pretrained",
]


def __getattr__(name: str) -> Any:
    if name == "Trellis2ImageTo3DPipeline":
        module = importlib.import_module(".pipelines", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__} has no attribute {name}")


def from_pretrained(path: str):
    module = importlib.import_module(".pipelines", __name__)
    return module.from_pretrained(path)
