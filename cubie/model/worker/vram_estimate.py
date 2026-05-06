from __future__ import annotations

import time

from cubie.model.worker import (
    maybe_empty_cuda_cache,
    normalize_model_name,
    normalize_optional_vram_mb,
    resolve_total_vram_mb,
)


class VRAMEstimateMixin:
    async def load_estimates_from_db(self) -> None:
        model_definition = await self._db_store.get_model(self.model_id)
        if model_definition is None:
            return

        weight_mb = normalize_optional_vram_mb(model_definition.get("weight_vram_mb"))
        total_vram_mb = resolve_total_vram_mb(model_definition)
        if weight_mb is None:
            if total_vram_mb is not None:
                weight_mb = max(int(round(total_vram_mb * 0.75)), 1)
            else:
                weight_mb = 1
        self.weight_vram_mb = max(weight_mb, 1)

        inference_mb = normalize_optional_vram_mb(model_definition.get("inference_vram_mb"))
        if inference_mb is None:
            if total_vram_mb is not None:
                inference_mb = max(total_vram_mb - self.weight_vram_mb, 1)
            else:
                inference_mb = 1
        self.inference_vram_mb = max(inference_mb, 1)

    async def persist_estimate(self, field_name: str, measured_mb: int) -> None:
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

    def on_inference_measured(
        self,
        callback_model_name: str,
        callback_device_id: str,
        inference_peak_mb: int,
    ) -> None:
        _ = callback_device_id
        normalized_model_name = normalize_model_name(callback_model_name)
        if normalized_model_name != self.model_id:
            return
        try:
            normalized_peak_mb = max(int(inference_peak_mb), 0)
        except (TypeError, ValueError):
            return
        setattr(self, "_last_inference_peak_mb", normalized_peak_mb)

    def consume_latest_inference_peak_mb(self) -> int | None:
        peak_mb = self._last_inference_peak_mb
        setattr(self, "_last_inference_peak_mb", None)
        return peak_mb

    async def apply_successful_inference_measurement(self) -> None:
        peak_mb = self.consume_latest_inference_peak_mb()
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
        await self.persist_estimate("inference_vram_mb", new_estimate)

    def resolve_oom_bump_target_mb(self) -> int:
        measured_reserved = self.consume_latest_inference_peak_mb()
        scaled_estimate = max(int(round(self.inference_vram_mb * 1.5)), 1)
        if measured_reserved is None:
            return scaled_estimate
        return max(int(measured_reserved), scaled_estimate, 1)

    async def apply_oom_bump_target_mb(self, target_mb: int) -> None:
        normalized_target_mb = max(int(target_mb), 1)
        if normalized_target_mb <= self.inference_vram_mb:
            return
        self.inference_vram_mb = normalized_target_mb
        await self.persist_estimate("inference_vram_mb", normalized_target_mb)

    def release_weight_allocation(self) -> None:
        if self._weight_allocation is not None:
            self._allocator.release_weight(self._weight_allocation.allocation_id)
        self._allocator.unregister_worker(self.model_id)
        setattr(self, "_weight_allocation", None)
        setattr(self, "_device_id", None)

    async def apply_measured_weight(self, measured_mb: int | None) -> None:
        if measured_mb is None or self._weight_allocation is None:
            return
        self._allocator.correct_weight(
            self._weight_allocation.allocation_id,
            measured_mb,
        )
        if measured_mb > self.weight_vram_mb:
            self.weight_vram_mb = measured_mb
            await self.persist_estimate("weight_vram_mb", measured_mb)

    def touch_last_used(self) -> None:
        setattr(self, "_last_used_tick", time.monotonic_ns())

    def empty_cuda_cache(self) -> None:
        maybe_empty_cuda_cache()

    def is_mock_runtime(self) -> bool:
        runtime = self._runtime
        if runtime is None:
            return False
        provider_name = runtime.provider.__class__.__name__.strip().lower()
        return provider_name.startswith("mock")
