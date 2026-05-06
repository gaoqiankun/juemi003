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
    kwargs: dict[str, object] = {
        "device_id": device_id,
        "measurement_callback": measurement_callback,
    }
    while True:
        try:
            maybe_runtime = gpu_worker_factory(model_id, **kwargs)
            if inspect.isawaitable(maybe_runtime):
                runtime = await maybe_runtime
            else:
                runtime = maybe_runtime
            return runtime
        except TypeError as exc:
            message = str(exc)
            if (
                "unexpected keyword argument 'measurement_callback'" in message
                and "measurement_callback" in kwargs
            ):
                kwargs.pop("measurement_callback", None)
                continue
            if "unexpected keyword argument 'device_id'" in message and "device_id" in kwargs:
                kwargs.pop("device_id", None)
                continue
            raise
