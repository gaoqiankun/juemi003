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
    def from_pretrained(cls, model_path: str) -> "MockStep1X3DProvider":
        _ = model_path
        return cls()

    def estimate_vram_mb(self, batch_size: int, options: dict) -> int:
        _ = options
        return batch_size * 27_000

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


class Step1X3DProvider:
    """Step1X-3D provider backed by the ``step1x3d_geometry`` and
    ``step1x3d_texture`` packages.

    Internally the model runs two stages (geometry generation via
    ``Step1X3DGeometryPipeline`` and texture synthesis via
    ``Step1X3DTexturePipeline``), but progress is emitted as the three
    canonical stages (ss -> shape -> material) expected by the pipeline.
    """

    def __init__(
        self,
        *,
        geometry_pipeline: Any,
        texture_pipeline: Any,
        model_path: str,
    ) -> None:
        self._geometry_pipeline = geometry_pipeline
        self._texture_pipeline = texture_pipeline
        self._model_path = model_path

    @classmethod
    def from_pretrained(cls, model_path: str) -> "Step1X3DProvider":
        report, geometry_pipeline, texture_pipeline = cls._inspect_runtime(
            model_path, load_pipeline=True,
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
        # Step1X-3D: geometry 1.3B + texture 3.5B ≈ 27 GB VRAM
        return int(27_000 * 1.2 * max(batch_size, 1))

    @property
    def stages(self) -> list[dict[str, float | str]]:
        return [
            {"name": "ss", "weight": 0.20},
            {"name": "shape", "weight": 0.45},
            {"name": "material", "weight": 0.35},
        ]

    async def run_batch(self, images, options, progress_cb=None, cancel_flags=None):
        _ = cancel_flags
        results: list[GenerationResult] = []
        for prepared_input in images:
            image = _extract_pil_image(prepared_input)
            try:
                mesh = await asyncio.to_thread(self._run_single, image, options)
            except ModelProviderExecutionError:
                raise
            except Exception as exc:
                raise ModelProviderExecutionError(
                    stage_name="gpu_run",
                    message=f"Step1X-3D inference failed: {exc}",
                ) from exc

            for stage_name in ("ss", "shape", "material"):
                await _emit_progress(progress_cb, stage_name)

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

    def _run_single(self, image: Any, options: dict[str, Any]) -> Any:
        num_steps = options.get("num_inference_steps", 50)
        guidance_scale = options.get("guidance_scale", 7.5)

        # Stage 1: Geometry generation
        output = self._geometry_pipeline(
            image,
            guidance_scale=guidance_scale,
            num_inference_steps=num_steps,
        )
        mesh = output.mesh[0] if hasattr(output, "mesh") else output

        # Stage 2: Texture synthesis (optional)
        if self._texture_pipeline is not None:
            # Step1X-3D texture pipeline may need post-processing utils
            try:
                utils = importlib.import_module(
                    "step1x3d_geometry.models.pipelines.pipeline_utils"
                )
                if hasattr(utils, "remove_degenerate_face"):
                    mesh = utils.remove_degenerate_face(mesh)
                if hasattr(utils, "reduce_face"):
                    mesh = utils.reduce_face(mesh)
            except (ModuleNotFoundError, AttributeError):
                pass

            texture_steps = options.get("texture_steps", 20)
            mesh = self._texture_pipeline(image, mesh, num_inference_steps=texture_steps)

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

        try:
            geo_pipelines = importlib.import_module(
                "step1x3d_geometry.models.pipelines.pipeline"
            )
        except ModuleNotFoundError as exc:
            raise ModelProviderConfigurationError(
                "real provider mode requires the 'step1x3d_geometry' package "
                "(install from https://github.com/stepfun-ai/Step1X-3D)"
            ) from exc

        geometry_cls = getattr(geo_pipelines, "Step1X3DGeometryPipeline", None)
        if geometry_cls is None:
            raise ModelProviderConfigurationError(
                "step1x3d_geometry.models.pipelines.pipeline.Step1X3DGeometryPipeline "
                "is not available"
            )
        report["geometry_pipeline_class"] = (
            f"{geo_pipelines.__name__}.{geometry_cls.__name__}"
        )

        texture_pipeline_cls = None
        try:
            tex_pipelines = importlib.import_module(
                "step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline"
            )
            texture_pipeline_cls = getattr(tex_pipelines, "Step1X3DTexturePipeline", None)
        except ModuleNotFoundError:
            pass
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
                        model_reference, subfolder=texture_subfolder,
                    )
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

    @staticmethod
    def _resolve_model_reference(model_path: str) -> tuple[str, str]:
        raw_value = model_path.strip()
        expanded_path = Path(raw_value).expanduser()
        has_local_path_hint = (
            raw_value.startswith(("/", ".", "~"))
            or raw_value.startswith("..")
        )

        if expanded_path.exists():
            return "local", str(expanded_path.resolve())

        if has_local_path_hint:
            raise ModelProviderConfigurationError(
                f"Step1X-3D model path does not exist: {model_path}"
            )

        return "huggingface", raw_value


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
