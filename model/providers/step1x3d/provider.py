from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import struct
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from gen3d.model.base import (
    GenerationResult,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
    ProviderDependency,
    StageProgress,
)

# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockStep1X3DProvider:
    """Drop-in mock for Step1X-3D that mirrors MockTrellis2Provider behaviour.

    Emits the canonical three GPU stages (ss, shape, material) so the existing
    pipeline / status-machine / API layer works unchanged.
    """

    def __init__(self, stage_delay_ms: int = 60) -> None:
        self._stage_delay_seconds = max(stage_delay_ms, 0) / 1000

    @classmethod
    def from_pretrained(
        cls,
        model_path: str,
        dep_paths: dict[str, str] | None = None,
    ) -> "MockStep1X3DProvider":
        _ = model_path
        _ = dep_paths
        return cls()

    def estimate_weight_vram_mb(self, options: dict[str, Any]) -> int:
        _ = options
        return 20_250

    def estimate_inference_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        _ = options
        return max(
            max(batch_size, 1) * 27_000 - self.estimate_weight_vram_mb(options),
            1,
        )

    def estimate_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        return self.estimate_weight_vram_mb(options) + self.estimate_inference_vram_mb(
            batch_size,
            options,
        )

    @property
    def stages(self) -> list[dict[str, float | str]]:
        return [
            {"name": "ss", "weight": 0.20},
            {"name": "shape", "weight": 0.45},
            {"name": "material", "weight": 0.35},
        ]

    async def run_batch(self, images, options, progress_cb=None, cancel_flags=None):
        _ = cancel_flags
        failure_stage = self.normalize_failure_stage(options.get("mock_failure_stage"))
        for stage_name in ("ss", "shape", "material"):
            if self._stage_delay_seconds:
                await asyncio.sleep(self._stage_delay_seconds)
            if failure_stage == stage_name:
                raise ModelProviderExecutionError(
                    stage_name=f"gpu_{stage_name}",
                    message=f"mock failure injected at gpu_{stage_name}",
                )
            await emit_progress(progress_cb, stage_name)
        return [
            GenerationResult(
                mesh={"mock_mesh": True, "input": image},
                metadata={"mock": True, "provider": "step1x3d", "resolution": options.get("resolution", 512)},
            )
            for image in images
        ]

    def export_glb(
        self,
        result: GenerationResult,
        output_path: str | Path,
        options: dict,
    ) -> None:
        _ = result
        _ = options
        Path(output_path).write_bytes(build_mock_glb_bytes())

    @staticmethod
    def normalize_failure_stage(value: Any) -> str | None:
        if value is None:
            return None
        stage = str(value).strip().lower()
        if stage.startswith("gpu_"):
            return stage.removeprefix("gpu_")
        return stage


# ---------------------------------------------------------------------------
# Real provider
# ---------------------------------------------------------------------------


class Step1X3DProvider:
    """Step1X-3D provider backed by the ``step1x3d_geometry`` and
    ``step1x3d_texture`` packages.

    Internally the model runs two stages (geometry generation via
    ``Step1X3DGeometryPipeline`` and texture synthesis via
    ``Step1X3DTexturePipeline``), but progress is emitted as the three
    canonical stages (ss -> shape -> material) expected by the pipeline.
    """

    _GEOMETRY_PIPELINE_MODULE = (
        "gen3d.model.providers.step1x3d.pipeline.step1x3d_geometry.models.pipelines.pipeline"
    )
    _TEXTURE_PIPELINE_MODULE = (
        "gen3d.model.providers.step1x3d.pipeline.step1x3d_texture.pipelines."
        "step1x_3d_texture_synthesis_pipeline"
    )
    _PIPELINE_UTILS_MODULE = (
        "gen3d.model.providers.step1x3d.pipeline.step1x3d_geometry.models.pipelines.pipeline_utils"
    )

    def __init__(
        self,
        *,
        geometry_pipeline: Any | None,
        texture_pipeline: Any | None,
        model_path: str,
    ) -> None:
        self._geometry_pipeline = geometry_pipeline
        self._texture_pipeline = texture_pipeline
        self._model_path = model_path

    @classmethod
    def dependencies(cls) -> list[ProviderDependency]:
        return [
            ProviderDependency(
                dep_id="sdxl-base-1.0",
                hf_repo_id="stabilityai/stable-diffusion-xl-base-1.0",
                description="SDXL base model for texture synthesis",
            ),
            ProviderDependency(
                dep_id="sdxl-vae-fp16",
                hf_repo_id="madebyollin/sdxl-vae-fp16-fix",
                description="SDXL VAE (fp16 fixed)",
            ),
            ProviderDependency(
                dep_id="birefnet",
                hf_repo_id="ZhengPeng7/BiRefNet",
                description="Background removal (shared)",
            ),
        ]

    @classmethod
    def from_pretrained(
        cls,
        model_path: str,
        dep_paths: dict[str, str],
    ) -> "Step1X3DProvider":
        resolved_dep_paths = cls.resolve_required_dep_paths(dep_paths)
        report, geometry_pipeline, texture_pipeline = cls.inspect_runtime_full(
            model_path,
            dep_paths=resolved_dep_paths,
            load_pipeline=True,
        )
        if geometry_pipeline is None:
            raise ModelProviderConfigurationError(
                f"failed to load Step1X-3D pipelines from {model_path}: unknown error"
            )
        return cls(
            geometry_pipeline=geometry_pipeline,
            texture_pipeline=texture_pipeline,
            model_path=str(report["model_path"]),
        )

    @classmethod
    def metadata_only(cls, model_path: str) -> "Step1X3DProvider":
        if not model_path:
            raise ModelProviderConfigurationError(
                "MODEL_PATH is required for real provider mode"
            )
        _, model_reference = cls.resolve_model_reference(model_path)
        return cls(
            geometry_pipeline=None,
            texture_pipeline=None,
            model_path=model_reference,
        )

    @classmethod
    def inspect_runtime(
        cls,
        model_path: str,
        *,
        dep_paths: dict[str, str] | None = None,
        load_pipeline: bool = True,
    ) -> dict[str, Any]:
        report, _, _ = cls.inspect_runtime_full(
            model_path,
            dep_paths=dep_paths,
            load_pipeline=load_pipeline,
        )
        return report

    def estimate_weight_vram_mb(self, options: dict[str, Any]) -> int:
        _ = options
        return int(27_000 * 1.2 * 0.75)

    def estimate_inference_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        _ = options
        total = int(27_000 * 1.2 * max(batch_size, 1))
        return max(total - self.estimate_weight_vram_mb(options), 1)

    def estimate_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        return self.estimate_weight_vram_mb(options) + self.estimate_inference_vram_mb(
            batch_size,
            options,
        )

    @property
    def stages(self) -> list[dict[str, float | str]]:
        return [
            {"name": "ss", "weight": 0.20},
            {"name": "shape", "weight": 0.45},
            {"name": "material", "weight": 0.35},
        ]

    async def run_batch(self, images, options, progress_cb=None, cancel_flags=None):
        _ = cancel_flags
        if self._geometry_pipeline is None:
            raise ModelProviderExecutionError(
                stage_name="gpu_run",
                message=(
                    "Step1X-3D metadata-only provider cannot run inference; "
                    "use ProcessGPUWorker subprocess provider"
                ),
            )
        loop = asyncio.get_running_loop()
        results: list[GenerationResult] = []
        for prepared_input in images:
            image = extract_pil_image(prepared_input)

            def emit_stage(stage_name: str) -> None:
                if progress_cb is None:
                    return
                asyncio.run_coroutine_threadsafe(
                    emit_progress(progress_cb, stage_name), loop
                )

            try:
                mesh = await asyncio.to_thread(self.run_single, image, options, emit_stage)
            except ModelProviderExecutionError:
                raise
            except Exception as exc:
                raise ModelProviderExecutionError(
                    stage_name="gpu_run",
                    message=f"Step1X-3D inference failed: {exc}",
                ) from exc

            results.append(
                GenerationResult(
                    mesh=mesh,
                    metadata={
                        "mock": False,
                        "provider": "step1x3d",
                        "model_path": self._model_path,
                        "resolution": options.get("resolution", 512),
                    },
                )
            )
        return results

    def export_glb(
        self,
        result: GenerationResult,
        output_path: str | Path,
        options: dict[str, Any],
    ) -> None:
        mesh = result.mesh
        try:
            if hasattr(mesh, "export"):
                mesh.export(str(output_path))
            else:
                trimesh = importlib.import_module("trimesh")
                if isinstance(mesh, (trimesh.Scene, trimesh.Trimesh)):
                    mesh.export(str(output_path), file_type="glb")
                else:
                    raise ModelProviderExecutionError(
                        stage_name="exporting",
                        message=(
                            "Step1X-3D result mesh does not support GLB export. "
                            f"Type: {type(mesh).__name__}"
                        ),
                    )
        except ModelProviderExecutionError:
            raise
        except Exception as exc:
            raise ModelProviderExecutionError(
                stage_name="exporting",
                message=f"Step1X-3D GLB export failed: {exc}",
            ) from exc

    def run_single(self, image: Any, options: dict[str, Any], emit_stage=None) -> Any:  # noqa: C901
        install_rembg_bria_alias_patch()
        num_steps = options.get("num_inference_steps", 25)
        guidance_scale = options.get("guidance_scale", 7.5)

        if emit_stage:
            emit_stage("ss")

        # Stage 1: Geometry generation
        output = self._geometry_pipeline(
            image,
            guidance_scale=guidance_scale,
            num_inference_steps=num_steps,
        )
        mesh = output.mesh[0] if hasattr(output, "mesh") else output

        if emit_stage:
            emit_stage("shape")

        # Stage 2: Texture synthesis (optional)
        if self._texture_pipeline is not None:
            # Free geometry inference activations before texture pipeline runs
            try:
                torch = importlib.import_module("torch")
            except ModuleNotFoundError:
                torch = None
            if (
                torch is not None
                and hasattr(torch, "cuda")
                and torch.cuda.is_available()
            ):
                torch.cuda.empty_cache()

            # Step1X-3D texture pipeline may need post-processing utils
            try:
                utils = importlib.import_module(self._PIPELINE_UTILS_MODULE)
                if hasattr(utils, "remove_degenerate_face"):
                    mesh = utils.remove_degenerate_face(mesh)
                if hasattr(utils, "reduce_face"):
                    mesh = utils.reduce_face(mesh)
            except (ModuleNotFoundError, AttributeError):
                pass

            texture_steps = options.get("texture_steps", 20)
            if hasattr(self._texture_pipeline, "config"):
                self._texture_pipeline.config.num_inference_steps = texture_steps
            mesh = self._texture_pipeline(image, mesh)

        if emit_stage:
            emit_stage("material")

        return mesh

    @classmethod
    def inspect_runtime_full(  # noqa: C901
        cls,
        model_path: str,
        *,
        dep_paths: dict[str, str] | None,
        load_pipeline: bool,
    ) -> tuple[dict[str, Any], Any | None, Any | None]:
        if not model_path:
            raise ModelProviderConfigurationError(
                "MODEL_PATH is required for real provider mode"
            )

        model_source, model_reference = cls.resolve_model_reference(model_path)

        report: dict[str, Any] = {
            "provider": "step1x3d",
            "model_path": model_reference,
            "model_source": model_source,
            "model_path_exists": model_source == "local",
            "load_pipeline": load_pipeline,
        }

        try:
            torch = importlib.import_module("torch")
        except ModuleNotFoundError as exc:
            raise ModelProviderConfigurationError(
                "real provider mode requires the 'torch' package"
            ) from exc

        report["torch_version"] = getattr(torch, "__version__", None)
        report["cuda_available"] = bool(torch.cuda.is_available())
        report["cuda_device_count"] = (
            int(torch.cuda.device_count()) if report["cuda_available"] else 0
        )
        if not report["cuda_available"]:
            raise ModelProviderConfigurationError(
                "real provider mode requires a CUDA-enabled torch runtime and visible GPU"
            )

        install_rembg_bria_alias_patch()

        try:
            geo_pipelines = importlib.import_module(cls._GEOMETRY_PIPELINE_MODULE)
        except ModuleNotFoundError as exc:
            raise ModelProviderConfigurationError(
                f"real provider mode requires the in-repo Step1X-3D geometry pipeline package"
                f" (ModuleNotFoundError: {exc})"
            ) from exc

        # Must be called AFTER importing the geometry pipeline so that all
        # submodules are already in sys.modules before we register aliases.
        install_step1x3d_geometry_alias()

        geometry_cls = getattr(geo_pipelines, "Step1X3DGeometryPipeline", None)
        if geometry_cls is None:
            raise ModelProviderConfigurationError(
                (
                    "gen3d.model.providers.step1x3d.pipeline.step1x3d_geometry.models."
                    "pipelines.pipeline.Step1X3DGeometryPipeline is not available"
                )
            )
        report["geometry_pipeline_class"] = (
            f"{geo_pipelines.__name__}.{geometry_cls.__name__}"
        )

        import logging as _logging
        _log = _logging.getLogger(__name__)

        texture_pipeline_cls = None
        try:
            tex_pipelines = importlib.import_module(cls._TEXTURE_PIPELINE_MODULE)
            texture_pipeline_cls = getattr(tex_pipelines, "Step1X3DTexturePipeline", None)
        except Exception as _tex_exc:
            _log.warning(
                "Step1X-3D texture pipeline module failed to import — "
                "texture synthesis will be disabled: %s",
                _tex_exc,
                exc_info=True,
            )
        report["texture_pipeline_class"] = (
            f"{tex_pipelines.__name__}.{texture_pipeline_cls.__name__}"
            if texture_pipeline_cls is not None
            else None
        )

        geometry_pipeline = None
        texture_pipeline = None
        if load_pipeline:
            geometry_subfolder = "Step1X-3D-Geometry-1300m"
            try:
                geometry_pipeline = geometry_cls.from_pretrained(
                    model_reference, subfolder=geometry_subfolder,
                )
                if hasattr(geometry_pipeline, "to"):
                    geometry_pipeline = geometry_pipeline.to("cuda")
            except Exception as exc:
                raise ModelProviderConfigurationError(
                    f"failed to load Step1X-3D geometry pipeline from "
                    f"{model_reference}/{geometry_subfolder}: {exc}"
                ) from exc

            if texture_pipeline_cls is not None:
                texture_subfolder = "Step1X-3D-Texture"
                try:
                    texture_pipeline = texture_pipeline_cls.from_pretrained(
                        model_reference,
                        subfolder=texture_subfolder,
                        base_model=dep_paths.get("sdxl-base-1.0") if dep_paths else None,
                        vae_model=dep_paths.get("sdxl-vae-fp16") if dep_paths else None,
                        birefnet_model=dep_paths.get("birefnet") if dep_paths else None,
                    )
                    if hasattr(texture_pipeline, "to"):
                        texture_pipeline = texture_pipeline.to("cuda")
                except Exception as exc:
                    raise ModelProviderConfigurationError(
                        f"failed to load Step1X-3D texture pipeline from "
                        f"{model_reference}/{texture_subfolder}: {exc}"
                    ) from exc

            report["geometry_pipeline_loaded"] = geometry_pipeline is not None
            report["texture_pipeline_loaded"] = texture_pipeline is not None
        else:
            report["geometry_pipeline_loaded"] = False
            report["texture_pipeline_loaded"] = False

        return report, geometry_pipeline, texture_pipeline

    @classmethod
    def resolve_required_dep_paths(
        cls,
        dep_paths: dict[str, str] | None,
    ) -> dict[str, str]:
        normalized_dep_paths = dep_paths or {}
        resolved: dict[str, str] = {}
        for dependency in cls.dependencies():
            raw_path = cls.require_dep_path(normalized_dep_paths, dependency.dep_id)
            resolved[dependency.dep_id] = str(Path(raw_path).expanduser())
        return resolved

    @staticmethod
    def require_dep_path(dep_paths: dict[str, str], dep_id: str) -> str:
        value = str(dep_paths.get(dep_id) or "").strip()
        if not value:
            raise ModelProviderConfigurationError(
                f"{dep_id} not in dep_paths, run Admin download first"
            )
        return value

    @staticmethod
    def resolve_model_reference(model_path: str) -> tuple[str, str]:
        raw_value = model_path.strip()
        resolved_path = Path(raw_value).expanduser().resolve()
        if not resolved_path.exists():
            raise ModelProviderConfigurationError(
                f"weights not found at {resolved_path}. Use Admin to download first."
            )
        return "local", str(resolved_path)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def build_mock_glb_bytes() -> bytes:
    """Emit a tiny but valid triangle mesh so the browser UI can preview mock outputs."""
    positions = (
        -0.6, -0.45, 0.0,
        0.6, -0.45, 0.0,
        0.0, 0.75, 0.0,
    )
    normals = (
        0.0, 0.0, 1.0,
        0.0, 0.0, 1.0,
        0.0, 0.0, 1.0,
    )
    binary_chunk = struct.pack("<18f", *(positions + normals))
    json_chunk = json.dumps(
        {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}],
            "meshes": [
                {
                    "primitives": [
                        {
                            "attributes": {
                                "POSITION": 0,
                                "NORMAL": 1,
                            }
                        }
                    ]
                }
            ],
            "buffers": [{"byteLength": len(binary_chunk)}],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": 36},
                {"buffer": 0, "byteOffset": 36, "byteLength": 36},
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "componentType": 5126,
                    "count": 3,
                    "type": "VEC3",
                    "min": [-0.6, -0.45, 0.0],
                    "max": [0.6, 0.75, 0.0],
                },
                {
                    "bufferView": 1,
                    "componentType": 5126,
                    "count": 3,
                    "type": "VEC3",
                },
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    json_padding = (4 - (len(json_chunk) % 4)) % 4
    json_chunk += b" " * json_padding

    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    return b"".join(
        [
            struct.pack("<III", 0x46546C67, 2, total_length),
            struct.pack("<I4s", len(json_chunk), b"JSON"),
            json_chunk,
            struct.pack("<I4s", len(binary_chunk), b"BIN\x00"),
            binary_chunk,
        ]
    )


async def emit_progress(progress_cb, stage_name: str) -> None:
    if progress_cb is None:
        return
    callback_result = progress_cb(
        StageProgress(
            stage_name=stage_name,
            step=1,
            total_steps=1,
        )
    )
    if inspect.isawaitable(callback_result):
        await callback_result


def extract_pil_image(prepared_input: Any) -> Any:
    if isinstance(prepared_input, dict) and "image" in prepared_input:
        return prepared_input["image"]
    return prepared_input


@contextmanager
def temporary_env_var(name: str, value: str | None):
    old_value = os.environ.get(name)
    if value:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old_value


def install_step1x3d_geometry_alias() -> None:
    """Register ``step1x3d_geometry.*`` as sys.modules aliases for our internal package.

    The HuggingFace checkpoint's model_index.json references components by the
    original package name ``step1x3d_geometry.*``. diffusers uses those strings
    verbatim with importlib.import_module. Since we moved the code into
    ``gen3d.model.providers.step1x3d.pipeline.step1x3d_geometry``, we register ALL
    already-loaded submodules under the old names so diffusers never re-executes
    module code (which would trigger duplicate @register calls).

    Must be called AFTER importing the geometry pipeline so that all submodules
    are already present in sys.modules.
    """
    import sys

    old_prefix = "step1x3d_geometry"
    new_prefix = "gen3d.model.providers.step1x3d.pipeline.step1x3d_geometry"

    if old_prefix in sys.modules:
        return

    for key, mod in list(sys.modules.items()):
        if key == new_prefix or key.startswith(new_prefix + "."):
            alias = old_prefix + key[len(new_prefix):]
            sys.modules.setdefault(alias, mod)


def install_rembg_bria_alias_patch() -> None:
    """Map legacy Step1X RMBG model name ``bria`` to rembg's ``bria-rmbg``.

    Step1X hardcodes ``model_name="bria"`` in preprocess_image. Newer rembg
    versions renamed this backend to ``bria-rmbg``, which raises:
    "No session class found for model 'bria'". This patch keeps compatibility
    and falls back to rembg's default backend when BRIA is unavailable.
    """

    try:
        rembg_module = importlib.import_module("rembg")
    except ModuleNotFoundError:
        return

    original_new_session = getattr(rembg_module, "new_session", None)
    if original_new_session is None:
        return
    if getattr(original_new_session, "_cubie3d_bria_alias_patch", False):
        return

    @wraps(original_new_session)
    def patched_new_session(*args, **kwargs):
        model_name = extract_requested_session_model_name(args, kwargs)
        if model_name == "bria":
            mapped_args, mapped_kwargs = replace_session_model_name(
                args,
                kwargs,
                "bria-rmbg",
            )
            try:
                return original_new_session(*mapped_args, **mapped_kwargs)
            except ValueError as exc:
                if "No session class found for model 'bria-rmbg'" not in str(exc):
                    raise
                fallback_args, fallback_kwargs = drop_session_model_name(
                    mapped_args,
                    mapped_kwargs,
                )
                return original_new_session(*fallback_args, **fallback_kwargs)
        return original_new_session(*args, **kwargs)

    setattr(patched_new_session, "_cubie3d_bria_alias_patch", True)
    rembg_module.new_session = patched_new_session

    # Keep module-level aliases in sync for versions where rembg exports
    # new_session from rembg.bg.
    try:
        rembg_bg_module = importlib.import_module("rembg.bg")
    except ModuleNotFoundError:
        return
    if hasattr(rembg_bg_module, "new_session"):
        rembg_bg_module.new_session = patched_new_session


def extract_requested_session_model_name(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str | None:
    if "model_name" in kwargs:
        value = kwargs.get("model_name")
    elif args:
        value = args[0]
    else:
        return None
    return str(value).strip().lower() if value is not None else None


def replace_session_model_name(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    model_name: str,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if "model_name" in kwargs:
        rewritten_kwargs = dict(kwargs)
        rewritten_kwargs["model_name"] = model_name
        return args, rewritten_kwargs

    if args:
        rewritten_args = list(args)
        rewritten_args[0] = model_name
        return tuple(rewritten_args), dict(kwargs)

    rewritten_kwargs = dict(kwargs)
    rewritten_kwargs["model_name"] = model_name
    return args, rewritten_kwargs


def drop_session_model_name(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    rewritten_kwargs = dict(kwargs)
    rewritten_kwargs.pop("model_name", None)
    if args:
        return tuple(args[1:]), rewritten_kwargs
    return args, rewritten_kwargs
