from __future__ import annotations

from cubie.vram.allocator import _logger


class MetricsMixin:
    def emit_acquire_result(
        self,
        *,
        device_id: str,
        outcome: str,
        wait_seconds: float,
    ) -> None:
        hook = self._metrics_hook
        if hook is None:
            return
        if hook.on_acquire_outcome is not None:
            try:
                hook.on_acquire_outcome(
                    device=device_id,
                    outcome=outcome,
                )
            except Exception as exc:
                _logger.warning(
                    "vram_allocator.metrics_hook_failed",
                    hook="on_acquire_outcome",
                    error=str(exc),
                )
        if hook.on_acquire_wait is not None:
            try:
                hook.on_acquire_wait(
                    device=device_id,
                    wait_seconds=max(wait_seconds, 0.0),
                )
            except Exception as exc:
                _logger.warning(
                    "vram_allocator.metrics_hook_failed",
                    hook="on_acquire_wait",
                    error=str(exc),
                )

    def emit_evict_result(
        self,
        *,
        device_id: str,
        result: str,
    ) -> None:
        hook = self._metrics_hook
        if hook is None or hook.on_evict is None:
            return
        try:
            hook.on_evict(device=device_id, result=result)
        except Exception as exc:
            _logger.warning(
                "vram_allocator.metrics_hook_failed",
                hook="on_evict",
                error=str(exc),
            )

    @staticmethod
    def wait_seconds(*, started_at: float | None, now: float) -> float:
        if started_at is None:
            return 0.0
        return max(now - started_at, 0.0)

    @staticmethod
    def resolve_success_outcome(
        *,
        evict_succeeded: bool,
        waited: bool,
    ) -> str:
        if evict_succeeded:
            return "after_evict"
        if waited:
            return "after_wait"
        return "immediate"
