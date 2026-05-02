from __future__ import annotations

from pathlib import Path
from typing import Any

_DEFAULT_SUBFOLDER = "hunyuan3d-paint-v2-0-turbo"
_DEFAULT_DELIGHT_SUBFOLDER = "hunyuan3d-delight-v2-0"


class Hunyuan3DPaintPipeline:
    """Texture-generation entry for HunYuan3D inference.

    Wraps the internal ``texgen.Hunyuan3DPaintPipeline`` (moved from
    ``hy3dgen.texgen``) so that the rest of the codebase never has to
    know about the internal texgen package layout.
    """

    def __init__(self, *, inner: Any) -> None:
        self._inner = inner

    @classmethod
    def from_pretrained(
        cls,
        model_path: str,
        *,
        subfolder: str = _DEFAULT_SUBFOLDER,
        delight_subfolder: str = _DEFAULT_DELIGHT_SUBFOLDER,
        **kwargs: Any,
    ) -> "Hunyuan3DPaintPipeline":
        resolved_path = _resolve_model_root(
            model_path=model_path,
            required_subfolders=[delight_subfolder, subfolder],
        )
        from cubie.model.providers.hunyuan3d.pipeline.texgen.pipelines import (
            Hunyuan3DPaintPipeline as _InnerPipeline,
        )
        inner = _InnerPipeline.from_pretrained(str(resolved_path), subfolder=subfolder)
        return cls(inner=inner)

    def to(self, device: str | None = None, dtype: Any | None = None) -> "Hunyuan3DPaintPipeline":
        if hasattr(self._inner, "to"):
            move_kwargs: dict[str, Any] = {}
            if device is not None:
                move_kwargs["device"] = device
            if dtype is not None:
                move_kwargs["dtype"] = dtype
            if move_kwargs:
                maybe = self._inner.to(**move_kwargs)
                if maybe is not None:
                    self._inner = maybe
        return self

    def cuda(self) -> "Hunyuan3DPaintPipeline":
        return self.to(device="cuda")

    def __call__(self, mesh: Any, image: Any) -> Any:
        return self._inner(mesh, image)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_model_root(
    *,
    model_path: str,
    required_subfolders: list[str],
) -> Path:
    model_root = Path(model_path).expanduser().resolve()
    if not model_root.exists():
        raise FileNotFoundError(
            f"HunYuan3D-2 texture weights not found at {model_root}. "
            "Use Admin to download model weights first."
        )
    missing_subfolders = [
        subfolder for subfolder in required_subfolders
        if not (model_root / subfolder).exists()
    ]
    if missing_subfolders:
        raise FileNotFoundError(
            f"HunYuan3D-2 texture assets missing under {model_root}: "
            + ", ".join(missing_subfolders)
            + ". Use Admin to download model weights first."
        )
    return model_root
