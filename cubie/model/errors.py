from __future__ import annotations


class ModelProviderConfigurationError(RuntimeError):
    pass


class ModelProviderExecutionError(RuntimeError):
    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(message)
        self.stage_name = stage_name


def friendly_model_error_message(error: Exception | None) -> str:
    raw_message = str(error or "").strip()
    lowered = raw_message.lower()
    if (
        "401" in lowered
        or "403" in lowered
        or "unauthorized" in lowered
        or "forbidden" in lowered
    ):
        return "模型需要授权访问，请配置 HuggingFace Token"
    if "timeout" in lowered or "connectionerror" in lowered or "connection error" in lowered:
        return "模型下载超时，请检查网络连接"
    if "no space left" in lowered or "disk" in lowered:
        return "磁盘空间不足"
    if "cuda out of memory" in lowered or " oom" in lowered or lowered == "oom":
        return "GPU 显存不足"
    if "path does not exist" in lowered:
        return "模型路径不存在，请检查配置"
    return raw_message or "模型加载失败"


__all__ = (
    "ModelProviderConfigurationError",
    "ModelProviderExecutionError",
    "friendly_model_error_message",
)
