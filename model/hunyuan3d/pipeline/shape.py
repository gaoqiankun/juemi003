from __future__ import annotations

import importlib
import inspect
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_ROOT = "~/.cache/hy3dgen"
_DEFAULT_CACHE_ENV = "HY3DGEN_MODELS"
_DEFAULT_SUBFOLDER = "hunyuan3d-dit-v2-0"
_DEFAULT_DTYPE = "float16"


class Hunyuan3DDiTFlowMatchingPipeline:
    """Self-maintained shape-generation entry for HunYuan3D-2 inference.

    This wrapper keeps the provider-facing API stable while avoiding runtime
    imports from the external source checkout. It resolves local/HF model
    assets and delegates to a diffusers-compatible pipeline implementation.
    """

    def __init__(
        self,
        *,
        pipeline: Any,
        model_root: Path,
        subfolder: str,
    ) -> None:
        self._pipeline = pipeline
        self._model_root = model_root
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
        _ = use_safetensors
        _ = variant
        resolved_dtype = _resolve_torch_dtype(dtype)
        model_root = _resolve_model_root(
            model_path=model_path,
            subfolder=subfolder,
            allow_patterns=[f"{subfolder}/*"],
        )
        pipeline = _load_diffusers_pipeline(
            model_root=model_root,
            subfolder=subfolder,
            torch_dtype=resolved_dtype,
            extra_kwargs=kwargs,
        )
        instance = cls(
            pipeline=pipeline,
            model_root=model_root,
            subfolder=subfolder,
        )
        if device:
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
                self._pipeline = self._pipeline.to(**move_kwargs)
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

    cache_root = Path(os.environ.get(_DEFAULT_CACHE_ENV, _DEFAULT_CACHE_ROOT)).expanduser()
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


def _load_diffusers_pipeline(
    *,
    model_root: Path,
    subfolder: str,
    torch_dtype: Any,
    extra_kwargs: dict[str, Any],
) -> Any:
    try:
        diffusers = importlib.import_module("diffusers")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "diffusers is required for HunYuan3D-2 shape inference runtime"
        ) from exc

    pipeline_cls = getattr(diffusers, "DiffusionPipeline", None)
    if pipeline_cls is None:
        raise RuntimeError("diffusers.DiffusionPipeline is not available")

    load_kwargs: dict[str, Any] = {
        "torch_dtype": torch_dtype,
        "trust_remote_code": True,
    }
    load_kwargs.update(extra_kwargs)
    if not (model_root / subfolder).exists():
        load_kwargs.pop("subfolder", None)
        return pipeline_cls.from_pretrained(str(model_root), **load_kwargs)
    return pipeline_cls.from_pretrained(
        str(model_root),
        subfolder=subfolder,
        **load_kwargs,
    )


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
