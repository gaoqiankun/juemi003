from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry(auto_describe=True)

_READY = Gauge(
    "cubify3d_ready",
    "Whether the Cubify 3D service is ready.",
    registry=REGISTRY,
)
_QUEUE_DEPTH = Gauge(
    "cubify3d_queue_depth",
    "Current number of queued tasks waiting to be processed.",
    registry=REGISTRY,
)
_GPU_SLOT_ACTIVE = Gauge(
    "cubify3d_gpu_slot_active",
    "Whether a GPU slot is actively running a task.",
    labelnames=("device",),
    registry=REGISTRY,
)
_TASK_DURATION = Histogram(
    "cubify3d_task_duration_seconds",
    "End-to-end task duration in seconds.",
    labelnames=("status",),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
    registry=REGISTRY,
)
_STAGE_DURATION = Histogram(
    "cubify3d_stage_duration_seconds",
    "Per-stage execution time in seconds.",
    labelnames=("stage",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    registry=REGISTRY,
)
_TASK_TOTAL = Counter(
    "cubify3d_task_total",
    "Total number of tasks by terminal status.",
    labelnames=("status",),
    registry=REGISTRY,
)
_WEBHOOK_TOTAL = Counter(
    "cubify3d_webhook_total",
    "Webhook delivery results.",
    labelnames=("result",),
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


def render_metrics(*, ready: bool) -> str:
    set_ready(ready)
    return generate_latest(REGISTRY).decode("utf-8")
