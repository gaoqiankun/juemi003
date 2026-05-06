from __future__ import annotations

import asyncio

from cubie.vram.allocator import DeviceBudget, _logger


class ProbeMixin:
    async def startprobe_loop(self) -> None:
        if self._vram_probe is None:
            return
        if self._probe_task is not None and not self._probe_task.done():
            return
        self._probe_task = asyncio.create_task(
            self.probe_loop(),
            name="vram-allocator-probe-loop",
        )

    async def stopprobe_loop(self) -> None:
        task = self._probe_task
        if task is None:
            return
        self._probe_task = None
        if task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def probe_loop(self) -> None:
        while True:
            await asyncio.sleep(self._PROBE_INTERVAL_SECONDS)
            await self.apply_external_baselines()

    async def apply_external_baselines(self) -> None:
        probe = self._vram_probe
        if probe is None:
            return
        async with self._lock:
            for device_id, budget in self._budgets.items():
                if budget.used_inference_vram_mb > 0:
                    continue
                try:
                    probed_free_mb = probe(device_id)
                except Exception as exc:
                    self._warn_probe_unavailable_once(exc)
                    continue
                if probed_free_mb is None:
                    continue
                self._update_baseline_for_device(
                    device_id=device_id,
                    budget=budget,
                    probed_free_mb=probed_free_mb,
                )

    def _warn_probe_unavailable_once(self, exc: Exception) -> None:
        if self._probe_warned_unavailable:
            return
        self._probe_warned_unavailable = True
        _logger.warning(
            "vram_allocator.probe_unavailable",
            error=str(exc),
        )

    def _update_baseline_for_device(
        self,
        *,
        device_id: str,
        budget: DeviceBudget,
        probed_free_mb: int,
    ) -> None:
        expected_free_mb = (
            budget.total_vram_mb
            - budget.reserved_vram_mb
            - budget.used_weight_vram_mb
        )
        external_observed_mb = max(expected_free_mb - max(int(probed_free_mb), 0), 0)
        baseline = self._external_baselines.get(device_id, 0)

        if external_observed_mb <= self._EXTERNAL_BASELINE_NOISE_MB:
            if baseline <= self._EXTERNAL_BASELINE_NOISE_MB:
                return  # Both small — genuine noise, no update needed
            # Observed dropped below noise floor but baseline is still large — decay toward zero
            self._external_baselines[device_id] = max(int(round(baseline * 0.5)), 0)
            return

        if external_observed_mb > baseline:
            baseline = int(round((0.8 * baseline) + (0.2 * external_observed_mb)))
        elif external_observed_mb < baseline * 0.5:
            baseline = int(round((0.5 * baseline) + (0.5 * external_observed_mb)))
        self._external_baselines[device_id] = max(baseline, 0)
