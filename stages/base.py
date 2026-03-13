from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from gen3d.engine.sequence import RequestSequence

StageUpdateHandler = Callable[
    [RequestSequence, str, dict[str, Any] | None],
    Awaitable[None],
]


class StageExecutionError(RuntimeError):
    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(message)
        self.stage_name = stage_name


class BaseStage(ABC):
    name: str

    @abstractmethod
    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
        raise NotImplementedError

    async def _emit_update(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None,
        *,
        event: str = "status_changed",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if on_update is None:
            return
        payload = metadata or {
            "status": sequence.status.value,
            "stage": sequence.current_stage,
        }
        await on_update(sequence, event, payload)
