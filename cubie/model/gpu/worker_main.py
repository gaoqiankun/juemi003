from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
from dataclasses import dataclass, field
from typing import Any

from cubie.model.base import (
    BaseModelProvider,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
)
from cubie.model.gpu.messaging import (
    deserialize_prepared_inputs,
    make_progress_publisher,
    send_error_response,
)
from cubie.model.providers.hunyuan3d.provider import Hunyuan3DProvider
from cubie.model.providers.step1x3d.provider import Step1X3DProvider
from cubie.model.providers.trellis2.provider import Trellis2Provider


@dataclass(slots=True)
class WorkerProcessConfig:
    provider_name: str
    model_path: str
    dep_paths: dict[str, str] = field(default_factory=dict)


def worker_process_main(
    device_id: str,
    request_queue: mp.Queue[dict[str, Any]],
    response_queue: mp.Queue[dict[str, Any]],
    process_config: WorkerProcessConfig,
) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = str(device_id)
    try:
        provider = build_process_provider(process_config)
    except Exception as exc:  # pragma: no cover - real runtime only
        response_queue.put({"type": "startup_error", "error": str(exc)})
        return

    torch_module, torch_device, weight_mb, inference_baseline_mb = (
        capture_cuda_baseline_mb()
    )
    response_queue.put({"type": "ready", "weight_allocated_mb": weight_mb})

    while True:
        message = request_queue.get()
        message_type = message.get("type")
        if message_type == "shutdown":
            response_queue.put({"type": "stopped"})
            return
        if message_type != "run":
            continue
        process_run_message(
            provider,
            response_queue,
            message,
            torch_module=torch_module,
            torch_device=torch_device,
            inference_baseline_mb=inference_baseline_mb,
        )


def process_run_message(
    provider: BaseModelProvider,
    response_queue: mp.Queue[dict[str, Any]],
    message: dict[str, Any],
    *,
    torch_module: Any | None,
    torch_device: Any | None,
    inference_baseline_mb: int | None,
) -> None:
    request_id = str(message["request_id"])
    prepared_inputs = deserialize_prepared_inputs(message["prepared_inputs"])
    options = dict(message["options"])
    progress_cb = make_progress_publisher(response_queue, request_id)

    if (
        torch_module is not None
        and torch_device is not None
        and inference_baseline_mb is not None
    ):
        reset_cuda_peak(torch_module, torch_device)

    try:
        results = asyncio.run(
            provider.run_batch(
                images=prepared_inputs,
                options=options,
                progress_cb=progress_cb,
            )
        )
    except ModelProviderExecutionError as exc:  # pragma: no cover - real runtime only
        send_error_response(response_queue, request_id, exc.stage_name, str(exc))
        return
    except Exception as exc:  # pragma: no cover - real runtime only
        send_error_response(response_queue, request_id, "gpu_run", str(exc))
        return

    response_queue.put(
        {
            "type": "result",
            "request_id": request_id,
            "results": results,
            "inference_peak_mb": measure_cuda_peak_mb(
                torch_module, torch_device, inference_baseline_mb
            ),
        }
    )

    del results
    prepared_inputs = []
    release_cuda_after_run(torch_module)


def reset_cuda_peak(torch_module: Any, torch_device: Any) -> None:
    try:
        torch_module.cuda.reset_peak_memory_stats(torch_device)
    except Exception:
        pass


def measure_cuda_peak_mb(
    torch_module: Any | None,
    torch_device: Any | None,
    baseline_mb: int | None,
) -> int | None:
    if torch_module is None or torch_device is None or baseline_mb is None:
        return None
    try:
        peak_mb = int(
            torch_module.cuda.max_memory_allocated(torch_device) / (1024 * 1024)
        )
        return max(0, peak_mb - baseline_mb)
    except Exception:
        return None


def release_cuda_after_run(torch_module: Any | None) -> None:
    import gc

    gc.collect()
    if torch_module is None:
        return
    try:
        torch_module.cuda.empty_cache()
    except Exception:
        pass


def capture_cuda_baseline_mb() -> tuple[Any | None, Any | None, int | None, int | None]:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return None, None, None, None

    try:
        if not torch.cuda.is_available():
            return torch, None, None, None
        device = torch.device("cuda")
        weight_reserved_mb = int(torch.cuda.memory_reserved(device) / (1024 * 1024))
        inference_baseline_allocated_mb = int(
            torch.cuda.memory_allocated(device) / (1024 * 1024)
        )
    except Exception:
        return torch, None, None, None
    return torch, device, weight_reserved_mb, inference_baseline_allocated_mb


def build_process_provider(process_config: WorkerProcessConfig) -> BaseModelProvider:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if process_config.provider_name == "trellis2":
        return Trellis2Provider.from_pretrained(
            process_config.model_path,
            dep_paths=process_config.dep_paths,
        )
    if process_config.provider_name == "hunyuan3d":
        return Hunyuan3DProvider.from_pretrained(
            process_config.model_path,
            dep_paths=process_config.dep_paths,
        )
    if process_config.provider_name == "step1x3d":
        return Step1X3DProvider.from_pretrained(
            process_config.model_path,
            dep_paths=process_config.dep_paths,
        )
    raise ModelProviderConfigurationError(
        f"unsupported MODEL_PROVIDER in GPU worker: {process_config.provider_name}"
    )
