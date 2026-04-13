from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)

_READY = Gauge(
    "ready",
    "Whether the Cubie 3D service is ready.",
    registry=REGISTRY,
)
_QUEUE_DEPTH = Gauge(
    "queue_depth",
    "Current number of queued tasks waiting to be processed.",
    registry=REGISTRY,
)
_GPU_SLOT_ACTIVE = Gauge(
    "gpu_slot_active",
    "Whether a GPU slot is actively running a task.",
    labelnames=("device",),
    registry=REGISTRY,
)
_TASK_DURATION = Histogram(
    "task_duration_seconds",
    "End-to-end task duration in seconds.",
    labelnames=("status",),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
    registry=REGISTRY,
)
_STAGE_DURATION = Histogram(
    "stage_duration_seconds",
    "Per-stage execution time in seconds.",
    labelnames=("stage",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    registry=REGISTRY,
)
_TASK_TOTAL = Counter(
    "task_total",
    "Total number of tasks by terminal status.",
    labelnames=("status",),
    registry=REGISTRY,
)
_WEBHOOK_TOTAL = Counter(
    "webhook_total",
    "Webhook delivery results.",
    labelnames=("result",),
    registry=REGISTRY,
)
_VRAM_ACQUIRE_INFERENCE_OUTCOMES = (
    "immediate",
    "after_wait",
    "after_evict",
    "timeout_internal",
    "timeout_external",
)
_VRAM_EVICT_RESULTS = ("success", "noop", "failure")
_VRAM_ACQUIRE_INFERENCE_TOTAL = Counter(
    "vram_acquire_inference_total",
    "Total acquire_inference outcomes by device.",
    labelnames=("device", "outcome"),
    registry=REGISTRY,
)
_VRAM_ACQUIRE_INFERENCE_WAIT = Histogram(
    "vram_acquire_inference_wait_seconds",
    "acquire_inference waiting time in seconds by device.",
    labelnames=("device",),
    buckets=(0.001, 0.01, 0.05, 0.25, 1, 5, 15, 30, 60, 120),
    registry=REGISTRY,
)
_VRAM_EVICT_TOTAL = Counter(
    "vram_evict_total",
    "VRAM eviction attempts by device and result.",
    labelnames=("device", "result"),
    registry=REGISTRY,
)

for status in ("succeeded", "failed", "cancelled"):
    _TASK_DURATION.labels(status=status)
    _TASK_TOTAL.labels(status=status)

for stage in ("preprocess", "gpu", "export"):
    _STAGE_DURATION.labels(stage=stage)

for result in ("success", "failure"):
    _WEBHOOK_TOTAL.labels(result=result)

_QUEUE_DEPTH.set(0)


def initialize_gpu_slots(device_ids: tuple[str, ...]) -> None:
    for device_id in dict.fromkeys(device_ids):
        _GPU_SLOT_ACTIVE.labels(device=str(device_id)).set(0)


def initialize_vram_metrics(device_ids: tuple[str, ...]) -> None:
    for device_id in dict.fromkeys(device_ids):
        normalized_device = str(device_id)
        _VRAM_ACQUIRE_INFERENCE_WAIT.labels(device=normalized_device)
        for outcome in _VRAM_ACQUIRE_INFERENCE_OUTCOMES:
            _VRAM_ACQUIRE_INFERENCE_TOTAL.labels(
                device=normalized_device,
                outcome=outcome,
            )
        for result in _VRAM_EVICT_RESULTS:
            _VRAM_EVICT_TOTAL.labels(
                device=normalized_device,
                result=result,
            )


def set_ready(ready: bool) -> None:
    _READY.set(1 if ready else 0)


def set_queue_depth(depth: int) -> None:
    _QUEUE_DEPTH.set(max(int(depth), 0))


def set_gpu_slot_active(*, device: str, active: bool) -> None:
    _GPU_SLOT_ACTIVE.labels(device=str(device)).set(1 if active else 0)


def observe_task_duration(*, status: str, duration_seconds: float) -> None:
    _TASK_DURATION.labels(status=status).observe(max(duration_seconds, 0.0))


def observe_stage_duration(*, stage: str, duration_seconds: float) -> None:
    _STAGE_DURATION.labels(stage=stage).observe(max(duration_seconds, 0.0))


def increment_task_total(*, status: str) -> None:
    _TASK_TOTAL.labels(status=status).inc()


def increment_webhook_total(*, result: str) -> None:
    _WEBHOOK_TOTAL.labels(result=result).inc()


def increment_vram_acquire_inference(*, device: str, outcome: str) -> None:
    _VRAM_ACQUIRE_INFERENCE_TOTAL.labels(
        device=str(device),
        outcome=str(outcome),
    ).inc()


def observe_vram_acquire_inference_wait(*, device: str, wait_seconds: float) -> None:
    _VRAM_ACQUIRE_INFERENCE_WAIT.labels(device=str(device)).observe(
        max(float(wait_seconds), 0.0)
    )


def increment_vram_evict(*, device: str, result: str) -> None:
    _VRAM_EVICT_TOTAL.labels(
        device=str(device),
        result=str(result),
    ).inc()


def render_metrics(*, ready: bool) -> str:
    set_ready(ready)
    return generate_latest(REGISTRY).decode("utf-8")
