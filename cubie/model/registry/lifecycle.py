from __future__ import annotations

import asyncio
import gc
from typing import Iterable

from cubie.model.registry import ModelRegistryLoadError, ModelRuntime
from cubie.model.registry.compat import (
    _ModelEntry,
    invoke_worker_factory,
    normalize_name,
    reset_entry,
)

_ORIGINAL_ASYNCIO_SLEEP = asyncio.sleep


class LifecycleMixin:
    async def close(self) -> None:
        async with self._lock:
            model_names = list(self._entries.keys())
        for model_name in model_names:
            await self.unload(model_name)

    def load(self, model_name: str, *, device_id: str | None = None) -> None:
        normalized = normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None:
            entry = _ModelEntry()
            self._entries[normalized] = entry

        if entry.state in {"loading", "ready"}:
            return

        entry.state = "loading"
        entry.error = None
        entry.event = asyncio.Event()
        entry.requested_device_id = (
            str(device_id).strip()
            if device_id is not None and str(device_id).strip()
            else None
        )
        entry.excluded_device_ids = ()
        entry.load_task = asyncio.create_task(
            self.load_worker(normalized, entry),
            name=f"model-load-{normalized}",
        )

    async def reload(
        self,
        model_name: str,
        *,
        exclude_device_ids: Iterable[str] | None = None,
    ) -> ModelRuntime:
        normalized = normalize_name(model_name)
        normalized_excluded_device_ids = tuple(
            normalized_device
            for raw_device_id in (exclude_device_ids or ())
            if (normalized_device := str(raw_device_id).strip())
        )
        async with self._lock:
            entry = self._entries.get(normalized)
            if entry is not None and entry.state == "loading" and entry.excluded_device_ids:
                pass
            else:
                await self.unload(normalized)
                entry = _ModelEntry(
                    state="loading",
                    event=asyncio.Event(),
                    excluded_device_ids=normalized_excluded_device_ids,
                )
                self._entries[normalized] = entry
                entry.load_task = asyncio.create_task(
                    self.load_worker(normalized, entry),
                    name=f"model-reload-{normalized}",
                )
        return await self.wait_ready(normalized)

    async def on_external_eviction(self, model_name: str) -> None:
        normalized = normalize_name(model_name)
        if not await self._reset_external_eviction_entry(normalized):
            return
        self._logger.info(
            "model.external_evicted",
            model_name=normalized,
        )
        await self.notify_model_unloaded(normalized)

    async def _recover_stale_ready_entry(self, model_name: str) -> None:
        if not await self._reset_external_eviction_entry(model_name):
            return
        self._logger.warning(
            "model.ready_entry_stale",
            model_name=model_name,
        )
        await self.notify_model_unloaded(model_name)
        self.load(model_name)

    async def _reset_external_eviction_entry(self, model_name: str) -> bool:
        async with self._lock:
            entry = self._entries.get(model_name)
            if entry is None:
                return False
            if entry.state == "not_loaded" and entry.worker is None:
                return False
            entry.worker = None
            reset_entry(entry)
        return True

    async def wait_ready(
        self,
        model_name: str,
        timeout_seconds: float = 1800.0,
    ) -> ModelRuntime:
        normalized = normalize_name(model_name)
        poll_interval = self._WAIT_READY_POLL_SECONDS
        timeout = max(float(timeout_seconds), 0.0)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while True:
            entry = self._entries.get(normalized)
            state = "not_loaded" if entry is None else entry.state

            if state == "ready":
                if entry is not None and entry.worker is not None:
                    if not entry.worker.weight_allocated:
                        await self._recover_stale_ready_entry(normalized)
                        continue
                    return entry.worker.runtime
                raise ModelRegistryLoadError(f"model {normalized} failed to load")

            if state == "error":
                message = f"model {normalized} failed to load"
                if entry is not None and entry.error is not None:
                    message = f"{message}: {entry.error}"
                raise ModelRegistryLoadError(message)

            remaining = deadline - loop.time()
            if remaining <= 0:
                if state == "not_loaded":
                    raise ModelRegistryLoadError(
                        f"model {normalized} still not loaded after timeout"
                    )
                raise ModelRegistryLoadError(
                    f"model {normalized} did not become ready before timeout"
                )

            await _ORIGINAL_ASYNCIO_SLEEP(min(poll_interval, remaining))

    async def unload(self, model_name: str) -> None:
        normalized = normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None:
            return
        if entry.state == "unloading":
            return
        had_runtime_or_task = entry.worker is not None or entry.load_task is not None
        entry.state = "unloading"

        load_task = entry.load_task
        if load_task is not None and not load_task.done():
            load_task.cancel()
            await asyncio.gather(load_task, return_exceptions=True)

        worker = entry.worker
        if worker is not None:
            await worker.unload()
            entry.worker = None

        reset_entry(entry)

        if worker is not None:
            del worker
            gc.collect()
            from cubie.model import registry as registry_api

            registry_api.maybe_empty_cuda_cache()

        self._logger.info(
            "model.unloaded",
            model_name=normalized,
        )
        if had_runtime_or_task:
            await self.notify_model_unloaded(normalized)

    async def load_worker(self, model_name: str, entry: _ModelEntry) -> None:
        try:
            worker = await invoke_worker_factory(
                self._worker_factory,
                model_name,
                device_id=entry.requested_device_id,
                exclude_device_ids=entry.excluded_device_ids or None,
            )
            await worker.load()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            entry.worker = None
            entry.error = exc
            entry.state = "error"
            self._logger.warning(
                "model.load_failed",
                model_name=model_name,
                error=str(exc),
            )
            await self.notify_model_unloaded(model_name)
        else:
            entry.worker = worker
            entry.error = None
            entry.state = "ready"
            self._logger.info(
                "model.ready",
                model_name=model_name,
                worker_count=1,
            )
            await self.notify_model_loaded(model_name)
        finally:
            entry.load_task = None
            entry.event.set()
