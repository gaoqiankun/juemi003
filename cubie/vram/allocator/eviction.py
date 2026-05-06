from __future__ import annotations

import asyncio
import inspect

from cubie.vram.allocator import (
    ModelWorkerInterface,
    _logger,
    normalize_device_id,
    normalize_model_name,
)


class EvictionMixin:
    async def evict_worker(
        self,
        *,
        device_id: str,
        requester_model_name: str,
        candidate_model_name: str,
        candidate_worker: ModelWorkerInterface,
    ) -> bool:
        normalized_candidate = normalize_model_name(candidate_model_name)
        try:
            await candidate_worker.evict()
        except Exception:
            self.emit_evict_result(device_id=device_id, result="failure")
            _logger.warning(
                "vram_allocator.evict_failed",
                device_id=device_id,
                requester_model_name=requester_model_name,
                candidate_model_name=candidate_model_name,
            )
            return False
        self.emit_evict_result(device_id=device_id, result="success")
        await self._dispatch_eviction_notification(normalized_candidate)
        return True

    async def _dispatch_eviction_notification(self, model_name: str) -> None:
        if not self._eviction_listeners:
            return
        if self._lock.locked():
            task = asyncio.create_task(
                self._notify_eviction_listeners(model_name),
                name=f"vram-eviction-notify-{model_name}",
            )
            self._eviction_listener_tasks.add(task)
            task.add_done_callback(self._eviction_listener_tasks.discard)
            return
        await self._notify_eviction_listeners(model_name)

    async def _notify_eviction_listeners(self, model_name: str) -> None:
        for listener in tuple(self._eviction_listeners):
            try:
                maybe_awaitable = listener(model_name)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
            except Exception as exc:
                _logger.warning(
                    "vram_allocator.eviction_listener_failed",
                    model_name=model_name,
                    error=str(exc),
                )

    def idle_candidates_on(
        self,
        device_id: str,
        exclude_model_id: str,
    ) -> list[tuple[str, ModelWorkerInterface]]:
        normalized_device = normalize_device_id(device_id)
        candidates: list[tuple[str, ModelWorkerInterface]] = []
        for model_id, worker in self._worker_registry.items():
            if model_id == exclude_model_id:
                continue
            candidate_device = normalize_device_id(getattr(worker, "device_id", ""))
            if candidate_device != normalized_device:
                continue
            if not bool(getattr(worker, "weight_allocated", False)):
                continue
            if bool(getattr(worker, "inference_busy", False)):
                continue
            if bool(getattr(worker, "evicting", False)):
                continue
            candidates.append((model_id, worker))
        candidates.sort(key=lambda item: int(getattr(item[1], "last_used_tick", 0)))
        return candidates
