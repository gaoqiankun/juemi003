from __future__ import annotations

from cubie.core.config import ServingConfig, ServingConfigurationError
from cubie.core.gpu import (
    get_gpu_device_info,
    normalize_persisted_disabled_devices,
    ordered_disabled_devices,
    parse_gpu_disabled_devices_update,
    resolve_device_ids,
)
from cubie.core.hf import is_hf_repo_id, normalize_hf_endpoint, set_hf_endpoint
from cubie.core.observability.logging import configure_logging
from cubie.core.observability.metrics import (
    increment_task_total,
    increment_vram_acquire_inference,
    increment_vram_evict,
    increment_webhook_total,
    initialize_gpu_slots,
    initialize_vram_metrics,
    observe_stage_duration,
    observe_task_duration,
    observe_vram_acquire_inference_wait,
    render_metrics,
    set_gpu_slot_active,
    set_queue_depth,
)
from cubie.core.pagination import (
    DEFAULT_CURSOR_PAGE_LIMIT,
    MAX_CURSOR_PAGE_LIMIT,
    CursorPageResult,
    normalize_cursor_page_limit,
)
from cubie.core.security import (
    RateLimitExceededError,
    TaskSubmissionValidationError,
    TokenRateLimiter,
    validate_callback_url,
    validate_image_url,
)

__all__ = (
    "CursorPageResult",
    "DEFAULT_CURSOR_PAGE_LIMIT",
    "MAX_CURSOR_PAGE_LIMIT",
    "RateLimitExceededError",
    "ServingConfig",
    "ServingConfigurationError",
    "TaskSubmissionValidationError",
    "TokenRateLimiter",
    "configure_logging",
    "get_gpu_device_info",
    "increment_task_total",
    "increment_vram_acquire_inference",
    "increment_vram_evict",
    "increment_webhook_total",
    "initialize_gpu_slots",
    "initialize_vram_metrics",
    "is_hf_repo_id",
    "normalize_hf_endpoint",
    "normalize_cursor_page_limit",
    "normalize_persisted_disabled_devices",
    "observe_stage_duration",
    "observe_task_duration",
    "observe_vram_acquire_inference_wait",
    "ordered_disabled_devices",
    "parse_gpu_disabled_devices_update",
    "render_metrics",
    "resolve_device_ids",
    "set_gpu_slot_active",
    "set_hf_endpoint",
    "set_queue_depth",
    "validate_callback_url",
    "validate_image_url",
)
