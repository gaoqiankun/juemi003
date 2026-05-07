from __future__ import annotations

import inspect
from typing import Callable

from cubie.model.worker import GPUWorkerFactory, _ModelRuntimeProtocol


async def invoke_gpu_worker_factory(
    model_id: str,
    gpu_worker_factory: GPUWorkerFactory,
    *,
    device_id: str,
    measurement_callback: Callable[[str, str, int], None],
) -> _ModelRuntimeProtocol:
    maybe_runtime = gpu_worker_factory(
        model_id,
        device_id=device_id,
        measurement_callback=measurement_callback,
    )
    if inspect.isawaitable(maybe_runtime):
        return await maybe_runtime
    return maybe_runtime
