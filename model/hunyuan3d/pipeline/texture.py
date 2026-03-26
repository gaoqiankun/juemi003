from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_ROOT = "~/.cache/cubie-models"
_DEFAULT_CACHE_ENV = "CUBIE_MODEL_CACHE"
_LEGACY_CACHE_ENV = "HY3DGEN_MODELS"
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
            allow_patterns=[
                f"{delight_subfolder}/*",
                f"{subfolder}/*",
            ],
        )
        from gen3d.model.hunyuan3d.pipeline.texgen.pipelines import (
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
    allow_patterns: list[str],
) -> Path:
    input_path = Path(model_path).expanduser()
    if input_path.exists():
        return input_path.resolve()

    for cache_root in _iter_cache_roots():
        candidate = cache_root / model_path
        if candidate.exists():
            if all((candidate / sub).exists() for sub in required_subfolders):
                return candidate.resolve()

    try:
        import huggingface_hub
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "huggingface_hub is required to download HunYuan3D-2 model assets"
        ) from exc

    snapshot_download = getattr(huggingface_hub, "snapshot_download", None)
    if snapshot_download is None:
        raise RuntimeError("huggingface_hub.snapshot_download is not available")

    logger.info(
        "Downloading HunYuan3D-2 texture assets from Hugging Face",
        extra={"repo_id": model_path, "subfolders": required_subfolders},
    )
    downloaded_root = Path(
        snapshot_download(
            repo_id=model_path,
            allow_patterns=allow_patterns,
        )
    )
    return downloaded_root.resolve()


def _iter_cache_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in (_DEFAULT_CACHE_ENV, _LEGACY_CACHE_ENV):
        env_value = os.environ.get(env_name)
        if not env_value:
            continue
        roots.append(Path(env_value).expanduser())
    roots.append(Path(_DEFAULT_CACHE_ROOT).expanduser())
    return roots
