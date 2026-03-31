from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import struct
from pathlib import Path
from typing import Any

from gen3d.model.base import (
    GenerationResult,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
    ProviderDependency,
    StageProgress,
)
from gen3d.model.hunyuan3d.pipeline.shape import Hunyuan3DDiTFlowMatchingPipeline
from gen3d.model.hunyuan3d.pipeline.texture import Hunyuan3DPaintPipeline

# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockHunyuan3DProvider:
    """Drop-in mock for HunYuan3D-2 that mirrors MockTrellis2Provider behaviour.

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
    ) -> "MockHunyuan3DProvider":
        _ = model_path
        _ = dep_paths
        return cls()

    def estimate_vram_mb(self, batch_size: int, options: dict) -> int:
        _ = options
        return batch_size * 24_000

    @property
    def stages(self) -> list[dict[str, float | str]]:
        return [
            {"name": "ss", "weight": 0.20},
            {"name": "shape", "weight": 0.45},
            {"name": "material", "weight": 0.35},
        ]

    async def run_batch(self, images, options, progress_cb=None, cancel_flags=None):
        _ = cancel_flags
        failure_stage = self._normalize_failure_stage(options.get("mock_failure_stage"))
        for stage_name in ("ss", "shape", "material"):
            if self._stage_delay_seconds:
                await asyncio.sleep(self._stage_delay_seconds)
            if failure_stage == stage_name:
                raise ModelProviderExecutionError(
                    stage_name=f"gpu_{stage_name}",
                    message=f"mock failure injected at gpu_{stage_name}",
                )
            await _emit_progress(progress_cb, stage_name)
        return [
            GenerationResult(
                mesh={"mock_mesh": True, "input": image},
                metadata={"mock": True, "provider": "hunyuan3d", "resolution": options.get("resolution", 512)},
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
        Path(output_path).write_bytes(_build_mock_glb_bytes())

    @staticmethod
    def _normalize_failure_stage(value: Any) -> str | None:
        if value is None:
            return None
        stage = str(value).strip().lower()
        if stage.startswith("gpu_"):
            return stage.removeprefix("gpu_")
        return stage


# ---------------------------------------------------------------------------
# Real provider
# ---------------------------------------------------------------------------


class Hunyuan3DProvider:
    """HunYuan3D-2 provider backed by in-repo pipeline wrappers.

    Internally the model runs two stages (shape generation via
    ``Hunyuan3DDiTFlowMatchingPipeline`` and texture painting via
    ``Hunyuan3DPaintPipeline``), but progress is emitted as the three
    canonical stages (ss → shape → material) expected by the pipeline.
    """

    def __init__(
        self,
        *,
        shape_pipeline: Any | None,
        texture_pipeline: Any | None,
        model_path: str,
    ) -> None:
        self._shape_pipeline = shape_pipeline
        self._texture_pipeline = texture_pipeline
        self._model_path = model_path

    @classmethod
    def dependencies(cls) -> list[ProviderDependency]:
        return []

    @classmethod
    def from_pretrained(
        cls,
        model_path: str,
        dep_paths: dict[str, str] | None = None,
    ) -> "Hunyuan3DProvider":
        _ = dep_paths
        report, shape_pipeline, texture_pipeline = cls._inspect_runtime(
            model_path, load_pipeline=True,
        )
        if shape_pipeline is None or texture_pipeline is None:
            raise ModelProviderConfigurationError(
                f"failed to load HunYuan3D-2 pipelines from {model_path}: unknown error"
            )
        return cls(
            shape_pipeline=shape_pipeline,
            texture_pipeline=texture_pipeline,
            model_path=str(report["model_path"]),
        )

    @classmethod
    def metadata_only(cls, model_path: str) -> "Hunyuan3DProvider":
        if not model_path:
            raise ModelProviderConfigurationError(
                "MODEL_PATH is required for real provider mode"
            )
        _, model_reference = cls._resolve_model_reference(model_path)
        return cls(
            shape_pipeline=None,
            texture_pipeline=None,
            model_path=model_reference,
        )

    @classmethod
    def inspect_runtime(
        cls,
        model_path: str,
        *,
        load_pipeline: bool = True,
    ) -> dict[str, Any]:
        report, _, _ = cls._inspect_runtime(model_path, load_pipeline=load_pipeline)
        return report

    def estimate_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        _ = options
        # HunYuan3D-2 typically requires ~24 GB VRAM for shape + texture.
        return int(24_000 * 1.2 * max(batch_size, 1))

    @property
    def stages(self) -> list[dict[str, float | str]]:
        return [
            {"name": "ss", "weight": 0.20},
            {"name": "shape", "weight": 0.45},
            {"name": "material", "weight": 0.35},
        ]

    async def run_batch(self, images, options, progress_cb=None, cancel_flags=None):
        _ = cancel_flags
        if self._shape_pipeline is None:
            raise ModelProviderExecutionError(
                stage_name="gpu_run",
                message=(
                    "HunYuan3D-2 metadata-only provider cannot run inference; "
                    "use ProcessGPUWorker subprocess provider"
                ),
            )
        loop = asyncio.get_running_loop()
        results: list[GenerationResult] = []
        for prepared_input in images:
            image = _extract_pil_image(prepared_input)

            def emit_stage(stage_name: str) -> None:
                if progress_cb is None:
                    return
                asyncio.run_coroutine_threadsafe(
                    _emit_progress(progress_cb, stage_name), loop
                )

            try:
                mesh = await asyncio.to_thread(self._run_single, image, options, emit_stage)
            except ModelProviderExecutionError:
                raise
            except Exception as exc:
                raise ModelProviderExecutionError(
                    stage_name="gpu_run",
                    message=f"HunYuan3D-2 inference failed: {exc}",
                ) from exc

            results.append(
                GenerationResult(
                    mesh=mesh,
                    metadata={
                        "mock": False,
                        "provider": "hunyuan3d",
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
                if isinstance(mesh, trimesh.Scene):
                    mesh.export(str(output_path))
                elif isinstance(mesh, trimesh.Trimesh):
                    mesh.export(str(output_path), file_type="glb")
                else:
                    raise ModelProviderExecutionError(
                        stage_name="exporting",
                        message=(
                            "HunYuan3D-2 result mesh does not support GLB export. "
                            f"Type: {type(mesh).__name__}"
                        ),
                    )
        except ModelProviderExecutionError:
            raise
        except Exception as exc:
            raise ModelProviderExecutionError(
                stage_name="exporting",
                message=f"HunYuan3D-2 GLB export failed: {exc}",
            ) from exc

    def _run_single(self, image: Any, options: dict[str, Any], emit_stage=None) -> Any:
        num_steps = options.get("num_steps", 25)
        guidance_scale = options.get("guidance_scale", 5.5)
        octree_resolution = options.get("octree_resolution", 256)

        if emit_stage:
            emit_stage("ss")

        out = self._shape_pipeline(
            image=image,
            num_inference_steps=num_steps,
            guidance_scale=guidance_scale,
            octree_resolution=octree_resolution,
        )
        mesh = out[0]

        if emit_stage:
            emit_stage("shape")

        if self._texture_pipeline is not None:
            mesh = self._texture_pipeline(mesh, image)

        if emit_stage:
            emit_stage("material")

        return mesh

    @classmethod
    def _inspect_runtime(
        cls,
        model_path: str,
        *,
        load_pipeline: bool,
    ) -> tuple[dict[str, Any], Any | None, Any | None]:
        if not model_path:
            raise ModelProviderConfigurationError(
                "MODEL_PATH is required for real provider mode"
            )

        model_source, model_reference = cls._resolve_model_reference(model_path)

        report: dict[str, Any] = {
            "provider": "hunyuan3d",
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

        shape_pipeline_cls = Hunyuan3DDiTFlowMatchingPipeline
        report["shape_pipeline_class"] = (
            f"{shape_pipeline_cls.__module__}.{shape_pipeline_cls.__name__}"
        )

        texture_pipeline_cls = Hunyuan3DPaintPipeline
        report["texture_pipeline_class"] = (
            f"{texture_pipeline_cls.__module__}.{texture_pipeline_cls.__name__}"
        )

        # Register sys.modules aliases so that class paths in config.yaml
        # (e.g. "hy3dgen.shapegen.models.autoencoders.model.ShapeVAE") resolve
        # to our internal package after shapegen is imported.
        _install_hy3dgen_alias()

        shape_pipeline = None
        texture_pipeline = None
        if load_pipeline:
            try:
                shape_pipeline = shape_pipeline_cls.from_pretrained(model_reference)
                if hasattr(shape_pipeline, "cuda"):
                    shape_pipeline.cuda()
            except Exception as exc:
                raise ModelProviderConfigurationError(
                    f"failed to load HunYuan3D-2 shape pipeline from {model_reference}: {exc}"
                ) from exc

            if texture_pipeline_cls is not None:
                try:
                    texture_pipeline = texture_pipeline_cls.from_pretrained(model_reference)
                    if hasattr(texture_pipeline, "cuda"):
                        texture_pipeline.cuda()
                except Exception as exc:
                    raise ModelProviderConfigurationError(
                        f"failed to load HunYuan3D-2 texture pipeline from {model_reference}: {exc}"
                    ) from exc

            report["shape_pipeline_loaded"] = shape_pipeline is not None
            report["texture_pipeline_loaded"] = texture_pipeline is not None
        else:
            report["shape_pipeline_loaded"] = False
            report["texture_pipeline_loaded"] = False

        return report, shape_pipeline, texture_pipeline

    @staticmethod
    def _resolve_model_reference(model_path: str) -> tuple[str, str]:
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


def _build_mock_glb_bytes() -> bytes:
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


async def _emit_progress(progress_cb, stage_name: str) -> None:
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


def _extract_pil_image(prepared_input: Any) -> Any:
    if isinstance(prepared_input, dict) and "image" in prepared_input:
        return prepared_input["image"]
    return prepared_input


def _install_hy3dgen_alias() -> None:
    """Register ``hy3dgen.shapegen.*``, ``hy3dshape.*``, and ``hy3dgen.texgen.*``
    as sys.modules aliases for our internal shapegen/texgen packages.

    config.yaml class paths (e.g. ``hy3dgen.shapegen.models.autoencoders.model.ShapeVAE``)
    are resolved via importlib at runtime.  Since we moved the code into
    ``gen3d.model.hunyuan3d.pipeline.shapegen`` and ``gen3d.model.hunyuan3d.pipeline.texgen``,
    we register all already-loaded submodules under the legacy names so that class
    resolution never re-executes module code.

    Must be called AFTER the shapegen package has been imported (which happens
    inside ``Hunyuan3DDiTFlowMatchingPipeline.from_pretrained``).
    """
    import sys

    aliases = [
        ("gen3d.model.hunyuan3d.pipeline.shapegen", "hy3dgen.shapegen"),
        ("gen3d.model.hunyuan3d.pipeline.shapegen", "hy3dshape"),
        ("gen3d.model.hunyuan3d.pipeline.texgen", "hy3dgen.texgen"),
    ]

    for new_prefix, old_prefix in aliases:
        if old_prefix in sys.modules:
            continue
        for key, mod in list(sys.modules.items()):
            if key == new_prefix or key.startswith(new_prefix + "."):
                alias = old_prefix + key[len(new_prefix):]
                sys.modules.setdefault(alias, mod)
