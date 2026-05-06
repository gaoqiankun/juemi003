from __future__ import annotations


class PrewarmMixin:
    def start_startup_prewarm(self, model_name: str) -> None:
        if not self._started:
            return
        self._model_registry.load(model_name)
        self._logger.info("model.prewarm_scheduled", model_name=model_name)
