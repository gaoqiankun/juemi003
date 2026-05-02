from __future__ import annotations

import threading

import structlog

_logger = structlog.get_logger(__name__)
_init_lock = threading.Lock()
_initialized = False
_init_failed = False


def ensure_initialized() -> bool:
    global _initialized, _init_failed

    if _initialized:
        return True
    if _init_failed:
        return False

    with _init_lock:
        if _initialized:
            return True
        if _init_failed:
            return False
        try:
            import pynvml  # type: ignore[import-not-found]

            pynvml.nvmlInit()
            _initialized = True
            _logger.info("vram_probe.initialized")
            return True
        except Exception as exc:
            _init_failed = True
            _logger.warning("vram_probe.init_failed", error=str(exc))
            return False


def probe_device_free_mb(device_id: str) -> int | None:
    """Return per-device free VRAM in MB, or None if probe is unavailable."""
    if not ensure_initialized():
        return None
    try:
        import pynvml  # type: ignore[import-not-found]

        index = int(device_id)
        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return int(info.free // (1024 * 1024))
    except Exception as exc:
        _logger.debug("vram_probe.query_failed", device_id=device_id, error=str(exc))
        return None
