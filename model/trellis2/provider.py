from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import struct
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from gen3d.model.base import (
    GenerationResult,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
    ProviderDependency,
    StageProgress,
)


class MockTrellis2Provider:
    def __init__(self, stage_delay_ms: int = 60) -> None:
        self._stage_delay_seconds = max(stage_delay_ms, 0) / 1000

    @classmethod
    def from_pretrained(
        cls,
        model_path: str,
        dep_paths: dict[str, str] | None = None,
    ) -> "MockTrellis2Provider":
        _ = model_path
        _ = dep_paths
        return cls()

    def estimate_weight_vram_mb(self, options: dict[str, Any]) -> int:
        _ = options
        return 15_000

    def estimate_inference_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        _ = options
        return max(
            max(batch_size, 1) * 20_000 - self.estimate_weight_vram_mb(options),
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
                metadata={"mock": True, "resolution": options.get("resolution", 1024)},
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


class Trellis2Provider:
    _PIPELINE_TYPES = {"512", "1024", "1024_cascade", "1536_cascade"}
    _PIPELINES_MODULE = "gen3d.model.trellis2.pipeline.pipelines"

    def __init__(
        self,
        *,
        pipeline: Any | None,
        model_path: str,
    ) -> None:
        self._pipeline = pipeline
        self._model_path = model_path

    @classmethod
    def dependencies(cls) -> list[ProviderDependency]:
        return [
            ProviderDependency(
                dep_id="trellis-image-large",
                hf_repo_id="microsoft/TRELLIS-image-large",
                description="TRELLIS sparse structure decoder checkpoint",
            ),
            ProviderDependency(
                dep_id="dinov3-vitl16",
                hf_repo_id="facebook/dinov3-vitl16-pretrain-lvd1689m",
                description="DINOv3 ViT-L/16 visual feature extractor",
            ),
            ProviderDependency(
                dep_id="rmbg-2.0",
                hf_repo_id="briaai/RMBG-2.0",
                description="Background removal (RMBG-2.0)",
            ),
        ]

    @classmethod
    def from_pretrained(
        cls,
        model_path: str,
        dep_paths: dict[str, str],
    ) -> "Trellis2Provider":
        resolved_dep_paths = cls.resolve_required_dep_paths(dep_paths)
        report, pipeline = cls.inspect_runtime_full(
            model_path,
            dep_paths=resolved_dep_paths,
            load_pipeline=True,
        )
        if pipeline is None:  # pragma: no cover - defensive fallback
            raise ModelProviderConfigurationError(
                f"failed to load TRELLIS2 pipeline from {model_path}: unknown error"
            )
        return cls(pipeline=pipeline, model_path=str(report["model_path"]))

    @classmethod
    def metadata_only(cls, model_path: str) -> "Trellis2Provider":
        if not model_path:
            raise ModelProviderConfigurationError(
                "MODEL_PATH is required for real provider mode"
            )
        _, model_reference = cls.resolve_model_reference(model_path)
        return cls(
            pipeline=None,
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
        report, _ = cls.inspect_runtime_full(
            model_path,
            dep_paths=dep_paths,
            load_pipeline=load_pipeline,
        )
        return report

    def estimate_weight_vram_mb(self, options: dict[str, Any]) -> int:
        _ = options
        return 16_000

    def estimate_inference_vram_mb(self, batch_size: int, options: dict[str, Any]) -> int:
        resolution = int(options.get("resolution", 1024))
        activation_base = {
            512: 4_000,
            1024: 6_000,
            1536: 10_000,
        }.get(resolution, 6_000)
        return max(activation_base * max(batch_size, 1), 1)

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
        if self._pipeline is None:
            raise ModelProviderExecutionError(
                stage_name="gpu_run",
                message=(
                    "TRELLIS2 metadata-only provider cannot run inference; "
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
            except Exception as exc:  # pragma: no cover - depends on external runtime
                raise ModelProviderExecutionError(
                    stage_name="gpu_run",
                    message=f"TRELLIS2 inference failed: {exc}",
                ) from exc
            results.append(
                GenerationResult(
                    mesh=mesh,
                    metadata={
                        "mock": False,
                        "provider": "trellis2",
                        "model_path": self._model_path,
                        "resolution": options.get("resolution", 1024),
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
        try:
            o_voxel = importlib.import_module("o_voxel")
        except ModuleNotFoundError as exc:
            raise ModelProviderExecutionError(
                stage_name="exporting",
                message="TRELLIS2 GLB export requires the 'o_voxel' package",
            ) from exc

        mesh = result.mesh
        required_fields = (
            "vertices",
            "faces",
            "attrs",
            "coords",
            "layout",
            "voxel_size",
        )
        missing = [field for field in required_fields if not hasattr(mesh, field)]
        if missing:
            raise ModelProviderExecutionError(
                stage_name="exporting",
                message=(
                    "TRELLIS2 result mesh is missing fields required for GLB export: "
                    + ", ".join(missing)
                ),
            )

        try:
            glb = o_voxel.postprocess.to_glb(
                vertices=mesh.vertices,
                faces=mesh.faces,
                attr_volume=mesh.attrs,
                coords=mesh.coords,
                attr_layout=mesh.layout,
                voxel_size=mesh.voxel_size,
                aabb=options.get(
                    "aabb",
                    [[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                ),
                decimation_target=options.get("decimation_target", 1_000_000),
                texture_size=options.get("texture_size", 4096),
                remesh=options.get("remesh", True),
                remesh_band=options.get("remesh_band", 1),
                remesh_project=options.get("remesh_project", 0),
                verbose=options.get("export_verbose", False),
            )
            try:
                glb.export(str(output_path), extension_webp=True)
            except KeyError:
                glb.export(str(output_path), extension_webp=False)
        except Exception as exc:  # pragma: no cover - depends on external runtime
            raise ModelProviderExecutionError(
                stage_name="exporting",
                message=f"TRELLIS2 GLB export failed: {exc}",
            ) from exc

    def run_single(self, image: Any, options: dict[str, Any], emit_stage=None) -> Any:
        pipeline_type = self.resolve_pipeline_type(options)

        run_kwargs: dict[str, Any] = {
            "pipeline_type": pipeline_type,
            "sparse_structure_sampler_params": {
                "steps": options.get("ss_steps", 12),
                "guidance_strength": options.get(
                    "ss_guidance_strength",
                    options.get("ss_guidance_scale", 7.5),
                ),
            },
            "shape_slat_sampler_params": {
                "steps": options.get("shape_steps", 20),
                "guidance_strength": options.get(
                    "shape_guidance_strength",
                    options.get("shape_guidance_scale", 7.5),
                ),
            },
            "tex_slat_sampler_params": {
                "steps": options.get("material_steps", 12),
                "guidance_strength": options.get(
                    "material_guidance_strength",
                    options.get("material_guidance_scale", 3.0),
                ),
            },
            "max_num_tokens": options.get("max_num_tokens", 49_152),
        }
        if emit_stage is not None:
            run_kwargs["stage_cb"] = emit_stage

        result = self._pipeline.run(image, **run_kwargs)

        return result[0]

    @classmethod
    def resolve_pipeline_type(cls, options: dict[str, Any]) -> str:
        explicit = options.get("pipeline_type")
        if explicit is not None:
            pipeline_type = str(explicit).strip()
            if pipeline_type not in cls._PIPELINE_TYPES:
                raise ModelProviderExecutionError(
                    stage_name="gpu_run",
                    message=(
                        "unsupported TRELLIS2 pipeline_type: "
                        f"{pipeline_type}. expected one of {sorted(cls._PIPELINE_TYPES)}"
                    ),
                )
            return pipeline_type

        resolution = int(options.get("resolution", 1024))
        return {
            512: "512",
            1024: "1024_cascade",
            1536: "1536_cascade",
        }.get(resolution, "1024_cascade")

    @classmethod
    def inspect_runtime_full(  # noqa: C901
        cls,
        model_path: str,
        *,
        dep_paths: dict[str, str] | None,
        load_pipeline: bool,
    ) -> tuple[dict[str, Any], Any | None]:
        if not model_path:
            raise ModelProviderConfigurationError("MODEL_PATH is required for real provider mode")

        model_source, model_reference = cls.resolve_model_reference(model_path)

        report: dict[str, Any] = {
            "provider": "trellis2",
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
            pipelines_module = importlib.import_module(cls._PIPELINES_MODULE)
        except ModuleNotFoundError as exc:
            raise ModelProviderConfigurationError(
                "real provider mode requires the in-repo TRELLIS2 pipeline package"
            ) from exc

        pipeline_cls = getattr(pipelines_module, "Trellis2ImageTo3DPipeline", None)
        if pipeline_cls is None:
            raise ModelProviderConfigurationError(
                (
                    "gen3d.model.trellis2.pipeline.pipelines."
                    "Trellis2ImageTo3DPipeline is not available"
                )
            )
        report["pipeline_class"] = (
            f"{pipelines_module.__name__}.{pipeline_cls.__name__}"
        )

        pipeline = None
        temp_config_path: Path | None = None
        if load_pipeline:
            try:
                pipeline_config_name = "pipeline.json"
                if dep_paths:
                    pipeline_config_name, temp_config_path = cls.build_pipeline_config_with_dep_paths(
                        model_reference=model_reference,
                        dep_paths=dep_paths,
                    )
                pipeline = pipeline_cls.from_pretrained(
                    model_reference,
                    config_file=pipeline_config_name,
                )
                if hasattr(pipeline, "cuda"):
                    pipeline.cuda()
            except Exception as exc:  # pragma: no cover - depends on external runtime
                raise ModelProviderConfigurationError(
                    f"failed to load TRELLIS2 pipeline from {model_reference}: {exc}"
                ) from exc
            finally:
                if temp_config_path is not None:
                    temp_config_path.unlink(missing_ok=True)
            report["pipeline_loaded"] = True
        else:
            report["pipeline_loaded"] = False

        return report, pipeline

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

    @classmethod
    def build_pipeline_config_with_dep_paths(
        cls,
        *,
        model_reference: str,
        dep_paths: dict[str, str],
    ) -> tuple[str, Path]:
        source_config_path = Path(model_reference) / "pipeline.json"
        if not source_config_path.exists():
            raise ModelProviderConfigurationError(
                f"pipeline config not found at {source_config_path}. Use Admin to download model weights first."
            )
        source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
        replaced_config = deepcopy(source_config)
        repo_to_local = {
            dependency.hf_repo_id: dep_paths[dependency.dep_id]
            for dependency in cls.dependencies()
            if dependency.dep_id in dep_paths
        }

        def replace_values(value: Any) -> Any:
            if isinstance(value, str):
                if value in repo_to_local:
                    return repo_to_local[value]
                for repo_id, local_path in repo_to_local.items():
                    if value.startswith(repo_id + "/"):
                        return local_path + value[len(repo_id):]
                return value
            if isinstance(value, list):
                return [replace_values(item) for item in value]
            if isinstance(value, dict):
                return {key: replace_values(item) for key, item in value.items()}
            return value

        replaced_config = replace_values(replaced_config)
        fd, temp_config_name = tempfile.mkstemp(
            prefix="pipeline-deps-",
            suffix=".json",
            dir=model_reference,
        )
        temp_config_path = Path(temp_config_name)
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            json.dump(replaced_config, temp_file)
        return temp_config_path.name, temp_config_path

    @staticmethod
    def resolve_model_reference(model_path: str) -> tuple[str, str]:
        raw_value = model_path.strip()
        resolved_path = Path(raw_value).expanduser().resolve()
        if not resolved_path.exists():
            raise ModelProviderConfigurationError(
                f"weights not found at {resolved_path}. Use Admin to download first."
            )
        return "local", str(resolved_path)


def build_mock_glb_bytes() -> bytes:
    # Emit a tiny but valid triangle mesh so the browser UI can preview mock outputs.
    positions = (
        -0.6,
        -0.45,
        0.0,
        0.6,
        -0.45,
        0.0,
        0.0,
        0.75,
        0.0,
    )
    normals = (
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        1.0,
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
                {
                    "buffer": 0,
                    "byteOffset": 0,
                    "byteLength": 36,
                },
                {
                    "buffer": 0,
                    "byteOffset": 36,
                    "byteLength": 36,
                },
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
