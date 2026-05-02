from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

_DEFAULT_SUBFOLDER = "hunyuan3d-dit-v2-0"
_DEFAULT_DTYPE = "float16"

_OWN_PKG = "gen3d.model.providers.hunyuan3d.pipeline.shapegen"


def _get_shapegen():
    """Import the shapegen package, applying sys.modules aliases before use."""
    import sys

    # Register hy3dgen.shapegen → our package so that class paths in config.yaml resolve.
    _register_alias("hy3dgen.shapegen", _OWN_PKG, sys)
    _register_alias("hy3dshape", _OWN_PKG, sys)

    return importlib.import_module(_OWN_PKG)


def _register_alias(old_prefix: str, new_prefix: str, sys_mod: Any) -> None:
    """Register sys.modules aliases: old_prefix.* → new_prefix.*"""
    import sys as _sys

    # Force-load the new package first so submodules are in sys.modules.
    try:
        importlib.import_module(new_prefix)
    except Exception:
        pass

    if old_prefix in _sys.modules:
        return

    for key, mod in list(_sys.modules.items()):
        if key == new_prefix or key.startswith(new_prefix + "."):
            alias = old_prefix + key[len(new_prefix):]
            _sys.modules.setdefault(alias, mod)


def get_obj_from_str(string: str) -> Any:
    """Import a class/function by dotted path string, with package prefix remapping."""
    remapped = _remap_class_path(string)
    module_path, cls_name = remapped.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)


def _remap_class_path(path: str) -> str:
    """Rewrite legacy class paths from config.yaml to our internal package."""
    replacements = [
        ("hy3dshape.", f"{_OWN_PKG}."),
        ("hy3dgen.shapegen.", f"{_OWN_PKG}."),
    ]
    for old, new in replacements:
        if path.startswith(old):
            return new + path[len(old):]
    return path


def instantiate_from_config(config: dict[str, Any], **kwargs: Any) -> Any:
    """Instantiate a class from a config dict with a ``target`` key."""
    if "target" not in config:
        raise KeyError("Expected key `target` to instantiate.")

    target = config["target"]
    try:
        cls = get_obj_from_str(target)
    except Exception as exc:
        # Try legacy remap as fallback
        try:
            remapped = target.replace("hy3dshape", "hy3dgen.shapegen")
            cls = get_obj_from_str(remapped)
        except Exception:
            raise exc

    params = config.get("params", {})
    kwargs.update(params)
    return cls(**kwargs)


class Hunyuan3DDiTFlowMatchingPipeline:
    """Shape-generation entry for HunYuan3D inference.

    Delegates to ``shapegen.Hunyuan3DDiTFlowMatchingPipeline`` from the
    in-repo shapegen package (gen3d.model.providers.hunyuan3d.pipeline.shapegen).

    Loading follows the checkpoint-style loading chain (config.yaml + weights)
    that the original Hunyuan3DDiTPipeline implements:
      from_pretrained → smart_load_model → resolve config_path + ckpt_path
      from_single_file → read config.yaml → instantiate_from_config each component
                       → load state_dict from safetensors / ckpt
    """

    def __init__(self, *, inner: Any) -> None:
        self._inner = inner

    @classmethod
    def from_pretrained(
        cls,
        model_path: str,
        *,
        subfolder: str = _DEFAULT_SUBFOLDER,
        use_safetensors: bool = True,
        variant: str | None = "fp16",
        dtype: Any | None = None,
        device: str | None = "cuda",
        **kwargs: Any,
    ) -> "Hunyuan3DDiTFlowMatchingPipeline":
        torch = importlib.import_module("torch")
        resolved_dtype = dtype if dtype is not None else getattr(torch, _DEFAULT_DTYPE)

        shapegen = _get_shapegen()
        inner_cls = shapegen.Hunyuan3DDiTFlowMatchingPipeline

        config_path, ckpt_path = _smart_load_model(
            model_path=model_path,
            subfolder=subfolder,
            use_safetensors=use_safetensors,
            variant=variant,
        )

        inner = inner_cls.from_single_file(
            ckpt_path,
            config_path,
            device=device,
            dtype=resolved_dtype,
            use_safetensors=use_safetensors,
            **kwargs,
        )
        return cls(inner=inner)

    def to(
        self, device: str | None = None, dtype: Any | None = None
    ) -> "Hunyuan3DDiTFlowMatchingPipeline":
        if hasattr(self._inner, "to"):
            kwargs: dict[str, Any] = {}
            if device is not None:
                kwargs["device"] = device
            if dtype is not None:
                kwargs["dtype"] = dtype
            if kwargs:
                self._inner.to(**kwargs)
        return self

    def cuda(self) -> "Hunyuan3DDiTFlowMatchingPipeline":
        return self.to(device="cuda")

    def __call__(self, **kwargs: Any) -> Any:
        return self._inner(**kwargs)


# ---------------------------------------------------------------------------
# Internal helpers mirroring hy3dgen.shapegen.utils.smart_load_model
# ---------------------------------------------------------------------------


def _smart_load_model(
    model_path: str,
    subfolder: str,
    use_safetensors: bool,
    variant: str | None,
) -> tuple[str, str]:
    """Resolve config.yaml and checkpoint paths from a local model path."""
    model_root = Path(model_path).expanduser().resolve()
    model_dir = model_root / subfolder
    if not model_dir.exists():
        raise FileNotFoundError(
            f"HunYuan3D-2 shape weights not found at {model_dir}. "
            "Use Admin to download model weights first."
        )
    return _build_asset_paths(model_dir, use_safetensors, variant)


def _build_asset_paths(
    model_dir: Path, use_safetensors: bool, variant: str | None
) -> tuple[str, str]:
    config_path = model_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.yaml under {model_dir}")

    extension = "safetensors" if use_safetensors else "ckpt"
    variant_suffix = f".{variant}" if variant else ""
    ckpt_name = f"model{variant_suffix}.{extension}"
    ckpt_path = model_dir / ckpt_name
    if not ckpt_path.exists():
        # Fallback: try without variant
        ckpt_path = model_dir / f"model.{extension}"
    if not ckpt_path.exists():
        raise FileNotFoundError(
            f"Unable to locate checkpoint under {model_dir}; tried {ckpt_name}"
        )
    return str(config_path), str(ckpt_path)
