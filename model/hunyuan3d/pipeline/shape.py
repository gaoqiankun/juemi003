from __future__ import annotations

import importlib
import inspect
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_ROOT = "~/.cache/cubie-models"
_DEFAULT_CACHE_ENV = "CUBIE_MODEL_CACHE"
_LEGACY_CACHE_ENV = "HY3DGEN_MODELS"
_DEFAULT_SUBFOLDER = "hunyuan3d-dit-v2-0"
_DEFAULT_DTYPE = "float16"


class Hunyuan3DDiTFlowMatchingPipeline:
    """Shape-generation entry for HunYuan3D inference.

    The loader follows checkpoint-style loading (config.yaml + model weights)
    instead of diffusers directory loading that requires model_index.json.
    """

    def __init__(
        self,
        *,
        pipeline: Any,
        model_root: Path,
        model_dir: Path,
        subfolder: str,
    ) -> None:
        self._pipeline = pipeline
        self._model_root = model_root
        self._model_dir = model_dir
        self._subfolder = subfolder

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
        resolved_dtype = _resolve_torch_dtype(dtype)
        model_root = _resolve_model_root(
            model_path=model_path,
            subfolder=subfolder,
            allow_patterns=[f"{subfolder}/*"],
        )
        model_dir = _resolve_subfolder(model_root=model_root, subfolder=subfolder)
        config_path, ckpt_path = _resolve_checkpoint_assets(
            model_dir=model_dir,
            use_safetensors=use_safetensors,
            variant=variant,
        )
        pipeline = _load_checkpoint_pipeline(
            ckpt_path=ckpt_path,
            config_path=config_path,
            model_dir=model_dir,
            torch_dtype=resolved_dtype,
            extra_kwargs=kwargs,
        )
        instance = cls(
            pipeline=pipeline,
            model_root=model_root,
            model_dir=model_dir,
            subfolder=subfolder,
        )
        if device or dtype is not None:
            instance.to(device=device, dtype=resolved_dtype)
        return instance

    def to(self, device: str | None = None, dtype: Any | None = None) -> "Hunyuan3DDiTFlowMatchingPipeline":
        if hasattr(self._pipeline, "to"):
            move_kwargs: dict[str, Any] = {}
            if device is not None:
                move_kwargs["device"] = device
            if dtype is not None:
                move_kwargs["dtype"] = dtype
            if move_kwargs:
                maybe_pipeline = self._pipeline.to(**move_kwargs)
                if maybe_pipeline is not None:
                    self._pipeline = maybe_pipeline
        return self

    def cuda(self) -> "Hunyuan3DDiTFlowMatchingPipeline":
        return self.to(device="cuda")

    def __call__(
        self,
        *,
        image: Any = None,
        num_inference_steps: int = 50,
        guidance_scale: float = 5.0,
        octree_resolution: int = 256,
        **kwargs: Any,
    ) -> list[Any]:
        call_kwargs = {
            "image": image,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "octree_resolution": octree_resolution,
        }
        call_kwargs.update(kwargs)
        output = _invoke_pipeline(self._pipeline, call_kwargs, image)
        return _coerce_mesh_list(output)


def _resolve_model_root(
    *,
    model_path: str,
    subfolder: str,
    allow_patterns: list[str],
) -> Path:
    input_path = Path(model_path).expanduser()
    if input_path.exists():
        return input_path.resolve()

    for cache_root in _iter_cache_roots():
        cache_candidate = cache_root / model_path
        if cache_candidate.exists():
            return cache_candidate.resolve()

    try:
        huggingface_hub = importlib.import_module("huggingface_hub")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "huggingface_hub is required to download HunYuan3D-2 model assets"
        ) from exc

    snapshot_download = getattr(huggingface_hub, "snapshot_download", None)
    if snapshot_download is None:
        raise RuntimeError("huggingface_hub.snapshot_download is not available")

    logger.info(
        "Downloading HunYuan3D-2 shape assets from Hugging Face",
        extra={"repo_id": model_path, "subfolder": subfolder},
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


def _resolve_subfolder(*, model_root: Path, subfolder: str) -> Path:
    candidate = model_root / subfolder
    if candidate.exists():
        return candidate
    return model_root


def _resolve_checkpoint_assets(
    *,
    model_dir: Path,
    use_safetensors: bool,
    variant: str | None,
) -> tuple[Path, Path]:
    config_path = model_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.yaml under {model_dir}")

    ckpt_candidates = _build_checkpoint_candidates(
        model_dir=model_dir,
        use_safetensors=use_safetensors,
        variant=variant,
    )
    for candidate in ckpt_candidates:
        if candidate.exists():
            return config_path, candidate

    attempted = ", ".join(str(path.name) for path in ckpt_candidates)
    raise FileNotFoundError(
        f"Unable to locate checkpoint under {model_dir}; tried: {attempted}"
    )


def _build_checkpoint_candidates(
    *,
    model_dir: Path,
    use_safetensors: bool,
    variant: str | None,
) -> list[Path]:
    preferred_extensions = ["safetensors", "ckpt"]
    if not use_safetensors:
        preferred_extensions = ["ckpt", "safetensors"]

    variant_suffixes: list[str] = []
    if variant:
        variant_suffixes.append(f".{variant}")
    variant_suffixes.append("")

    candidates: list[Path] = []
    for extension in preferred_extensions:
        for suffix in variant_suffixes:
            candidates.append(model_dir / f"model{suffix}.{extension}")
    return candidates


def _load_checkpoint_pipeline(
    *,
    ckpt_path: Path,
    config_path: Path,
    model_dir: Path,
    torch_dtype: Any,
    extra_kwargs: dict[str, Any],
) -> Any:
    try:
        diffusers = importlib.import_module("diffusers")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "diffusers is required for HunYuan3D shape inference runtime"
        ) from exc

    pipeline_cls = getattr(diffusers, "DiffusionPipeline", None)
    if pipeline_cls is None:
        raise RuntimeError("diffusers.DiffusionPipeline is not available")

    from_single_file = getattr(pipeline_cls, "from_single_file", None)
    if from_single_file is None:
        raise RuntimeError(
            "diffusers.DiffusionPipeline.from_single_file is required for checkpoint loading"
        )

    load_kwargs: dict[str, Any] = {
        "torch_dtype": torch_dtype,
        "trust_remote_code": True,
        "config": str(model_dir),
        "original_config_file": str(config_path),
    }
    load_kwargs.update(extra_kwargs)

    filtered_kwargs = _filter_kwargs(from_single_file, _drop_none_values(load_kwargs))
    try:
        return from_single_file(str(ckpt_path), **filtered_kwargs)
    except Exception as exc:
        raise RuntimeError(
            f"failed to load HunYuan3D shape checkpoint from {ckpt_path}: {exc}"
        ) from exc


def _resolve_torch_dtype(dtype: Any | None) -> Any:
    if dtype is not None:
        return dtype
    try:
        torch = importlib.import_module("torch")
    except ModuleNotFoundError as exc:
        raise RuntimeError("torch is required for HunYuan3D-2 shape inference runtime") from exc
    return getattr(torch, _DEFAULT_DTYPE)


def _invoke_pipeline(pipeline: Any, call_kwargs: dict[str, Any], image: Any) -> Any:
    filtered_kwargs = _filter_kwargs(pipeline, call_kwargs)
    try:
        return pipeline(**filtered_kwargs)
    except TypeError:
        fallback_kwargs = dict(filtered_kwargs)
        fallback_kwargs.pop("image", None)
        return pipeline(image, **fallback_kwargs)


def _filter_kwargs(callable_obj: Any, values: dict[str, Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return dict(values)
    parameters = signature.parameters.values()
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters):
        return dict(values)
    accepted_names = {param.name for param in parameters}
    return {key: value for key, value in values.items() if key in accepted_names}


def _drop_none_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _coerce_mesh_list(output: Any) -> list[Any]:
    if isinstance(output, list):
        return output
    if isinstance(output, tuple):
        if output and isinstance(output[0], list):
            return output[0]
        return list(output)
    if isinstance(output, dict):
        extracted = _extract_mapping_value(output)
        if extracted is not None:
            return extracted
        return [output]
    extracted = _extract_object_value(output)
    if extracted is not None:
        return extracted
    return [output]


def _extract_mapping_value(output: dict[str, Any]) -> list[Any] | None:
    for key in ("mesh", "meshes", "result", "results"):
        value = output.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            return value
        return [value]
    return None


def _extract_object_value(output: Any) -> list[Any] | None:
    for attr in ("mesh", "meshes", "result", "results"):
        if not hasattr(output, attr):
            continue
        value = getattr(output, attr)
        if isinstance(value, list):
            return value
        if value is not None:
            return [value]
    return None
