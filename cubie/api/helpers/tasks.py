from __future__ import annotations

_TASK_STATUS_MAP: dict[str, str] = {
    "queued": "queued",
    "preprocessing": "queued",
    "gpu_queued": "queued",
    "gpu_ss": "live",
    "gpu_shape": "live",
    "gpu_material": "live",
    "exporting": "live",
    "uploading": "live",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "failed",
}

def map_task_status(backend_status: str) -> str:
    return _TASK_STATUS_MAP.get(backend_status, "queued")
