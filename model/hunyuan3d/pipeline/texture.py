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
_DEFAULT_SUBFOLDER = "hunyuan3d-paint-v2-0-turbo"
_DEFAULT_DELIGHT_SUBFOLDER = "hunyuan3d-delight-v2-0"
_DEFAULT_DTYPE = "float16"


class Hunyuan3DPaintPipeline:
    """Texture-generation entry for HunYuan3D inference."""

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
        delight_subfolder: str = _DEFAULT_DELIGHT_SUBFOLDER,
        use_safetensors: bool = True,
        variant: str | None = "fp16",
        dtype: Any | None = None,
        device: str | None = "cuda",
        **kwargs: Any,
    ) -> "Hunyuan3DPaintPipeline":
        resolved_dtype = _resolve_torch_dtype(dtype)
        model_root = _resolve_model_root(
            model_path=model_path,
            required_subfolders=[delight_subfolder, subfolder],
            allow_patterns=[
                f"{delight_subfolder}/*",
                f"{subfolder}/*",
            ],
        )
        pipeline = _load_texture_pipeline(
            model_root=model_root,
            subfolder=subfolder,
            delight_subfolder=delight_subfolder,
            use_safetensors=use_safetensors,
            variant=variant,
            torch_dtype=resolved_dtype,
            extra_kwargs=kwargs,
        )
        instance = cls(
            pipeline=pipeline,
            model_root=model_root,
            subfolder=subfolder,
        )
        if device or dtype is not None:
            instance.to(device=device, dtype=resolved_dtype)
        return instance

    def to(self, device: str | None = None, dtype: Any | None = None) -> "Hunyuan3DPaintPipeline":
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

    def cuda(self) -> "Hunyuan3DPaintPipeline":
        return self.to(device="cuda")

    def __call__(self, mesh: Any, image: Any) -> Any:
        output = _invoke_texture_pipeline(self._pipeline, mesh=mesh, image=image)
        textured_mesh = _extract_textured_mesh(output)
        if textured_mesh is None:
            return mesh
        return textured_mesh


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
        cache_candidate = cache_root / model_path
        if cache_candidate.exists():
            if all((cache_candidate / subfolder).exists() for subfolder in required_subfolders):
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


def _load_texture_pipeline(
    *,
    model_root: Path,
    subfolder: str,
    delight_subfolder: str,
    use_safetensors: bool,
    variant: str | None,
    torch_dtype: Any,
    extra_kwargs: dict[str, Any],
) -> Any:
    try:
        diffusers = importlib.import_module("diffusers")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "diffusers is required for HunYuan3D texture inference runtime"
        ) from exc

    pipeline_cls = getattr(diffusers, "DiffusionPipeline", None)
    if pipeline_cls is None:
        raise RuntimeError("diffusers.DiffusionPipeline is not available")

    base_kwargs: dict[str, Any] = {
        "torch_dtype": torch_dtype,
        "trust_remote_code": True,
        "delight_subfolder": delight_subfolder,
    }
    base_kwargs.update(extra_kwargs)

    from_pretrained = getattr(pipeline_cls, "from_pretrained")
    pretrain_kwargs = _filter_kwargs(from_pretrained, _drop_none_values({
        **base_kwargs,
        "subfolder": subfolder,
    }))
    try:
        return from_pretrained(str(model_root), **pretrain_kwargs)
    except Exception as from_pretrained_error:
        model_dir = _resolve_subfolder(model_root=model_root, subfolder=subfolder)
        config_path, ckpt_path = _resolve_checkpoint_assets(
            model_dir=model_dir,
            use_safetensors=use_safetensors,
            variant=variant,
        )

        from_single_file = getattr(pipeline_cls, "from_single_file", None)
        if from_single_file is None:
            raise RuntimeError(
                "failed to load texture pipeline from checkpoint and "
                "diffusers.DiffusionPipeline.from_single_file is unavailable"
            ) from from_pretrained_error

        single_file_kwargs = _filter_kwargs(
            from_single_file,
            _drop_none_values(
                {
                    **base_kwargs,
                    "config": str(model_dir),
                    "original_config_file": str(config_path),
                    "subfolder": subfolder,
                    "delight_subfolder": delight_subfolder,
                    "delight_model_path": str(model_root / delight_subfolder),
                }
            ),
        )
        try:
            return from_single_file(str(ckpt_path), **single_file_kwargs)
        except Exception as from_single_file_error:
            raise RuntimeError(
                "failed to load HunYuan3D texture checkpoint "
                f"from {ckpt_path}: {from_single_file_error}"
            ) from from_pretrained_error


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


def _resolve_torch_dtype(dtype: Any | None) -> Any:
    if dtype is not None:
        return dtype
    try:
        torch = importlib.import_module("torch")
    except ModuleNotFoundError as exc:
        raise RuntimeError("torch is required for HunYuan3D-2 texture inference runtime") from exc
    return getattr(torch, _DEFAULT_DTYPE)


def _invoke_texture_pipeline(pipeline: Any, *, mesh: Any, image: Any) -> Any:
    attempts: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
        ((mesh, image), {}),
        ((), {"mesh": mesh, "image": image}),
        ((mesh,), {"image": image}),
        ((), {"image": image, "input_mesh": mesh}),
    )
    last_error: Exception | None = None
    for args, kwargs in attempts:
        try:
            filtered_kwargs = _filter_kwargs(pipeline, kwargs)
            return pipeline(*args, **filtered_kwargs)
        except TypeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError("HunYuan3D-2 texture pipeline invocation failed")


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


def _extract_textured_mesh(output: Any) -> Any | None:
    if output is None:
        return None
    if isinstance(output, tuple):
        return _first_or_none(output)
    if isinstance(output, list):
        return _first_or_none(output)
    if isinstance(output, dict):
        extracted = _extract_mapping_value(output)
        if extracted is not None:
            return extracted
    extracted = _extract_object_value(output)
    if extracted is not None:
        return extracted
    return output


def _extract_mapping_value(output: dict[str, Any]) -> Any | None:
    for key in ("mesh", "meshes", "result", "results"):
        value = output.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            return _first_or_none(value)
        return value
    return None


def _extract_object_value(output: Any) -> Any | None:
    for attr in ("mesh", "meshes", "result", "results"):
        if not hasattr(output, attr):
            continue
        value = getattr(output, attr)
        if value is None:
            continue
        if isinstance(value, list):
            return _first_or_none(value)
        return value
    return None


def _first_or_none(values: list[Any] | tuple[Any, ...]) -> Any | None:
    if not values:
        return None
    return values[0]
