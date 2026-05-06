from __future__ import annotations

import inspect
from typing import Awaitable, Callable

ModelLoadedListener = Callable[[str], Awaitable[None] | None]
ModelUnloadedListener = Callable[[str], Awaitable[None] | None]


class ListenersMixin:
    def add_model_loaded_listener(self, listener: ModelLoadedListener) -> None:
        self._model_loaded_listeners.append(listener)

    def add_model_unloaded_listener(self, listener: ModelUnloadedListener) -> None:
        self._model_unloaded_listeners.append(listener)

    def add_weight_measured_listener(self, listener) -> None:
        # Deprecated: kept as no-op compatibility API.
        _ = listener

    async def notify_model_loaded(self, model_name: str) -> None:
        for listener in self._model_loaded_listeners:
            try:
                maybe_awaitable = listener(model_name)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
            except Exception as exc:
                self._logger.warning(
                    "model.loaded_listener_failed",
                    model_name=model_name,
                    error=str(exc),
                )

    async def notify_model_unloaded(self, model_name: str) -> None:
        for listener in self._model_unloaded_listeners:
            try:
                maybe_awaitable = listener(model_name)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
            except Exception as exc:
                self._logger.warning(
                    "model.unloaded_listener_failed",
                    model_name=model_name,
                    error=str(exc),
                )
