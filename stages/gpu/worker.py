from __future__ import annotations

from gen3d.model.base import BaseModelProvider, GenerationResult


class GPUWorker:
    def __init__(self, worker_id: str, provider: BaseModelProvider) -> None:
        self.worker_id = worker_id
        self._provider = provider

    async def run_batch(
        self,
        prepared_inputs: list[object],
        options: dict,
        progress_cb=None,
    ) -> list[GenerationResult]:
        return await self._provider.run_batch(
            images=prepared_inputs,
            options=options,
            progress_cb=progress_cb,
        )
