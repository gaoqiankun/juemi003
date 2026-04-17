from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable, Protocol, cast

import structlog
from gen3d.engine.vram_allocator import (
    InferenceAllocation,
    VRAMAllocator,
    WeightAllocation,
    WeightAllocationID,
)
from gen3d.model.base import GenerationResult, ModelProviderExecutionError, StageProgress
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.worker import GPUWorkerHandle


class _ModelStoreProtocol(Protocol):
    async def get_model(self, model_id: str) -> dict[str, Any] | None: ...

    async def update_model(self, model_id: str, **updates: object) -> dict[str, Any] | None: ...


class _ModelRuntimeProtocol(Protocol):
    model_name: str
    provider: Any
    workers: list[GPUWorkerHandle]
    scheduler: GPUSlotScheduler
    assigned_device_id: str | None
    weight_vram_mb: int | None


GPUWorkerFactory = Callable[..., _ModelRuntimeProtocol | Awaitable[_ModelRuntimeProtocol]]


def _normalize_model_name(model_id: str) -> str:
    return str(model_id).strip().lower()


def _normalize_optional_vram_mb(value: object) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if normalized < 0:
        return None
    return normalized


def _resolve_total_vram_mb(model_definition: dict[str, Any]) -> int | None:
    raw_vram_gb = model_definition.get("vram_gb")
    if raw_vram_gb is not None:
        try:
            parsed = float(raw_vram_gb)
        except (TypeError, ValueError):
            parsed = 0.0
        if parsed > 0:
            return int(round(parsed * 1024.0))
    min_vram = _normalize_optional_vram_mb(model_definition.get("min_vram_mb"))
    return min_vram


def _looks_like_oom(error: BaseException) -> bool:
    message = str(error).lower()
    return "out of memory" in message or "cuda oom" in message or "cuda out of memory" in message


def _maybe_empty_cuda_cache() -> None:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


class _ModelWorkerSchedulerAdapter:
    def __init__(self, owner: "ModelWorker") -> None:
        self._owner = owner

    @property
    def worker_id(self) -> str:
        return self._owner.worker_id

    @property
    def device_id(self) -> str:
        return self._owner.device_id or ""

    @property
    def startup_weight_mb(self) -> int | None:
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run_batch(
        self,
        prepared_inputs: list[object],
        options: dict,
        progress_cb=None,
    ) -> list[GenerationResult]:
        callback = cast(Callable[[StageProgress], Awaitable[None] | None] | None, progress_cb)
        return await self._owner.run_inference(
            batch=prepared_inputs,
            options=options,
            progress_cb=callback,
        )


class ModelWorker:
    _EVICT_POLL_SECONDS = 0.05
    _INFERENCE_EMA_OLD_WEIGHT = 0.7
    _INFERENCE_EMA_NEW_WEIGHT = 0.3

    def __init__(
        self,
        model_id: str,
        allocator: VRAMAllocator,
        gpu_worker_factory: GPUWorkerFactory,
        db_store: _ModelStoreProtocol,
    ) -> None:
        self.model_id = _normalize_model_name(model_id)
        self._allocator = allocator
        self._gpu_worker_factory = gpu_worker_factory
        self._db_store = db_store
        self._logger = structlog.get_logger(__name__)
        self._weight_allocated = False
        self._inference_busy = False
        self._evicting = False
        self.weight_vram_mb = 1
        self.inference_vram_mb = 1
        self._weight_allocation: WeightAllocation | None = None
        self._device_id: str | None = None
        self._gpu_worker: GPUWorkerHandle | None = None
        self._runtime: _ModelRuntimeProtocol | None = None
        self._runtime_adapter = _ModelWorkerSchedulerAdapter(self)
        self._load_lock = asyncio.Lock()
        self._last_inference_peak_mb: int | None = None
        self._last_used_tick = time.monotonic_ns()

    @property
    def worker_id(self) -> str:
        if self._gpu_worker is not None:
            return str(self._gpu_worker.worker_id)
        return f"model-worker-{self.model_id}"

    @property
    def device_id(self) -> str | None:
        return self._device_id

    @property
    def runtime(self) -> _ModelRuntimeProtocol:
        if self._runtime is None:
            raise RuntimeError(f"model {self.model_id} is not loaded")
        return self._runtime

    @property
    def weight_allocated(self) -> bool:
        return self._weight_allocated

    @property
    def inference_busy(self) -> bool:
        return self._inference_busy

    @property
    def evicting(self) -> bool:
        return self._evicting

    @property
    def last_used_tick(self) -> int:
        return self._last_used_tick

    async def load(self) -> None:
        async with self._load_lock:
            if self._weight_allocated:
                return
            await self._load_estimates_from_db()
            self._weight_allocation = await self._allocator.request_weight(
                self.model_id,
                self.weight_vram_mb,
            )
            self._device_id = self._weight_allocation.device_id
            self._allocator.register_worker(self.model_id, self)
            measured_weight_mb: int | None = None
            try:
                measured_weight_mb = await self._start_runtime_on(self._device_id)
            except Exception:
                if self._weight_allocation is not None:
                    self._allocator.release_weight(self._weight_allocation.allocation_id)
                self._allocator.unregister_worker(self.model_id)
                self._weight_allocation = None
                self._device_id = None
                raise

            if self._weight_allocation is None:
                raise RuntimeError(f"model {self.model_id} has no weight allocation after load")
            if measured_weight_mb is not None:
                self._allocator.correct_weight(
                    self._weight_allocation.allocation_id,
                    measured_weight_mb,
                )
                if measured_weight_mb > self.weight_vram_mb:
                    self.weight_vram_mb = measured_weight_mb
                    await self._persist_estimate("weight_vram_mb", measured_weight_mb)
            if self._is_mock_runtime():
                self.inference_vram_mb = 1
            self._weight_allocated = True
            self._touch_last_used()

    async def evict(self) -> None:
        if self._evicting:
            return
        self._evicting = True
        try:
            while self._inference_busy:
                await asyncio.sleep(self._EVICT_POLL_SECONDS)
            await self._stop_runtime()
            if self._weight_allocation is not None:
                self._allocator.release_weight(self._weight_allocation.allocation_id)
            self._allocator.unregister_worker(self.model_id)
            self._weight_allocation = None
            self._device_id = None
            self._weight_allocated = False
        finally:
            self._evicting = False

    async def unload(self) -> None:
        await self.evict()

    async def run_inference(
        self,
        *,
        batch: list[object],
        options: dict[str, Any],
        progress_cb: Callable[[StageProgress], Awaitable[None] | None] | None,
    ) -> list[GenerationResult]:
        if self._evicting:
            raise RuntimeError(f"model {self.model_id} is evicting")
        if self._gpu_worker is None or self._device_id is None:
            raise RuntimeError(f"model {self.model_id} has no running GPU worker")

        self._inference_busy = True
        self._touch_last_used()
        inference_allocation: InferenceAllocation | None = None
        try:
            inference_allocation = await self._allocator.request_inference(
                model_id=self.model_id,
                device_id=self._device_id,
                inference_mb=self.inference_vram_mb,
                weight_mb=self.weight_vram_mb,
            )
            if inference_allocation.weight_allocation_id is not None:
                await self._do_migration(
                    new_device=inference_allocation.device_id,
                    new_weight_alloc=inference_allocation.weight_allocation_id,
                    new_inference_alloc=inference_allocation.inference_allocation_id,
                )

            try:
                results = await self._run_batch(batch=batch, options=options, progress_cb=progress_cb)
            except Exception as exc:
                if not _looks_like_oom(exc):
                    raise
                bump_target_mb = self._resolve_oom_bump_target_mb()
                self.inference_vram_mb = bump_target_mb
                await self._persist_estimate("inference_vram_mb", bump_target_mb)
                _maybe_empty_cuda_cache()
                if inference_allocation is not None:
                    self._allocator.release_inference(inference_allocation.inference_allocation_id)
                    inference_allocation = None
                inference_allocation = await self._allocator.request_inference(
                    model_id=self.model_id,
                    device_id=self._device_id or "",
                    inference_mb=bump_target_mb,
                    weight_mb=self.weight_vram_mb,
                )
                if inference_allocation.weight_allocation_id is not None:
                    await self._do_migration(
                        new_device=inference_allocation.device_id,
                        new_weight_alloc=inference_allocation.weight_allocation_id,
                        new_inference_alloc=inference_allocation.inference_allocation_id,
                    )
                results = await self._run_batch(
                    batch=batch,
                    options=options,
                    progress_cb=progress_cb,
                )

            await self._apply_successful_inference_measurement()
            _maybe_empty_cuda_cache()
            return results
        finally:
            if inference_allocation is not None:
                self._allocator.release_inference(inference_allocation.inference_allocation_id)
            self._inference_busy = False
            self._touch_last_used()

    async def _do_migration(
        self,
        new_device: str,
        new_weight_alloc: WeightAllocationID,
        new_inference_alloc,
    ) -> None:
        _ = new_inference_alloc
        old_weight_alloc = self._weight_allocation
        self._weight_allocated = False
        await self._stop_runtime()
        if old_weight_alloc is not None:
            self._allocator.release_weight(old_weight_alloc.allocation_id)
        self._allocator.unregister_worker(self.model_id)

        measured_weight_mb: int | None = None
        self._device_id = str(new_device).strip()
        self._weight_allocation = WeightAllocation(
            allocation_id=new_weight_alloc,
            device_id=self._device_id,
        )
        try:
            measured_weight_mb = await self._start_runtime_on(self._device_id)
        except Exception:
            # Migration failed after old runtime teardown; keep worker unregistered.
            self._weight_allocation = None
            self._device_id = None
            raise

        self._allocator.register_worker(self.model_id, self)
        self._weight_allocated = True
        if measured_weight_mb is not None:
            self._allocator.correct_weight(new_weight_alloc, measured_weight_mb)
            if measured_weight_mb > self.weight_vram_mb:
                self.weight_vram_mb = measured_weight_mb
                await self._persist_estimate("weight_vram_mb", measured_weight_mb)
        if self._is_mock_runtime():
            self.inference_vram_mb = 1
        self._touch_last_used()

    async def _run_batch(
        self,
        *,
        batch: list[object],
        options: dict[str, Any],
        progress_cb: Callable[[StageProgress], Awaitable[None] | None] | None,
    ) -> list[GenerationResult]:
        if self._gpu_worker is None:
            raise RuntimeError(f"model {self.model_id} has no running GPU worker")
        return await self._gpu_worker.run_batch(
            prepared_inputs=batch,
            options=options,
            progress_cb=progress_cb,
        )

    async def _start_runtime_on(self, device_id: str) -> int | None:
        runtime = await self._invoke_gpu_worker_factory(device_id=device_id)
        if not runtime.workers:
            raise RuntimeError(f"model {self.model_id} runtime returned no workers")

        for worker in runtime.workers:
            await worker.start()

        runtime.scheduler = GPUSlotScheduler([cast(GPUWorkerHandle, self._runtime_adapter)])
        runtime.assigned_device_id = str(device_id).strip()
        runtime.weight_vram_mb = self.weight_vram_mb

        self._runtime = runtime
        self._gpu_worker = runtime.workers[0]
        self._device_id = runtime.assigned_device_id
        startup_weight_mb = getattr(self._gpu_worker, "startup_weight_mb", None)
        if startup_weight_mb is None:
            return None
        try:
            return max(int(startup_weight_mb), 0)
        except (TypeError, ValueError):
            return None

    async def _stop_runtime(self) -> None:
        runtime = self._runtime
        if runtime is None:
            self._gpu_worker = None
            return
        scheduler_shutdown = getattr(runtime.scheduler, "shutdown", None)
        if callable(scheduler_shutdown):
            scheduler_shutdown()
        for worker in runtime.workers:
            await worker.stop()
        self._gpu_worker = None
        self._runtime = None
        _maybe_empty_cuda_cache()

    async def _invoke_gpu_worker_factory(self, *, device_id: str) -> _ModelRuntimeProtocol:
        kwargs: dict[str, object] = {
            "device_id": device_id,
            "measurement_callback": self._on_inference_measured,
        }
        while True:
            try:
                maybe_runtime = self._gpu_worker_factory(self.model_id, **kwargs)
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

    async def _load_estimates_from_db(self) -> None:
        model_definition = await self._db_store.get_model(self.model_id)
        if model_definition is None:
            return

        weight_mb = _normalize_optional_vram_mb(model_definition.get("weight_vram_mb"))
        total_vram_mb = _resolve_total_vram_mb(model_definition)
        if weight_mb is None:
            if total_vram_mb is not None:
                weight_mb = max(int(round(total_vram_mb * 0.75)), 1)
            else:
                weight_mb = 1
        self.weight_vram_mb = max(weight_mb, 1)

        inference_mb = _normalize_optional_vram_mb(model_definition.get("inference_vram_mb"))
        if inference_mb is None:
            if total_vram_mb is not None:
                inference_mb = max(total_vram_mb - self.weight_vram_mb, 1)
            else:
                inference_mb = 1
        self.inference_vram_mb = max(inference_mb, 1)

    async def _persist_estimate(self, field_name: str, measured_mb: int) -> None:
        normalized_value = max(int(measured_mb), 0)
        try:
            await self._db_store.update_model(
                self.model_id,
                **{field_name: normalized_value},
            )
        except Exception as exc:
            self._logger.warning(
                "model_worker.persist_estimate_failed",
                model_id=self.model_id,
                field_name=field_name,
                measured_mb=normalized_value,
                error=str(exc),
            )

    async def _apply_successful_inference_measurement(self) -> None:
        peak_mb = self._consume_latest_inference_peak_mb()
        if peak_mb is None:
            return
        new_estimate = max(
            int(
                round(
                    (self._INFERENCE_EMA_OLD_WEIGHT * self.inference_vram_mb)
                    + (self._INFERENCE_EMA_NEW_WEIGHT * peak_mb)
                )
            ),
            int(peak_mb),
        )
        if new_estimate <= self.inference_vram_mb:
            return
        self.inference_vram_mb = new_estimate
        await self._persist_estimate("inference_vram_mb", new_estimate)

    def _resolve_oom_bump_target_mb(self) -> int:
        measured_reserved = self._consume_latest_inference_peak_mb()
        scaled_estimate = max(int(round(self.inference_vram_mb * 1.5)), 1)
        if measured_reserved is None:
            return scaled_estimate
        return max(int(measured_reserved), scaled_estimate, 1)

    def _on_inference_measured(
        self,
        callback_model_name: str,
        callback_device_id: str,
        inference_peak_mb: int,
    ) -> None:
        _ = callback_device_id
        normalized_model_name = _normalize_model_name(callback_model_name)
        if normalized_model_name != self.model_id:
            return
        try:
            normalized_peak_mb = max(int(inference_peak_mb), 0)
        except (TypeError, ValueError):
            return
        self._last_inference_peak_mb = normalized_peak_mb

    def _consume_latest_inference_peak_mb(self) -> int | None:
        peak_mb = self._last_inference_peak_mb
        self._last_inference_peak_mb = None
        return peak_mb

    def _touch_last_used(self) -> None:
        self._last_used_tick = time.monotonic_ns()

    def _is_mock_runtime(self) -> bool:
        runtime = self._runtime
        if runtime is None:
            return False
        provider_name = runtime.provider.__class__.__name__.strip().lower()
        return provider_name.startswith("mock")
