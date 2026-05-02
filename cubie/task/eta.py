from __future__ import annotations

import math
from datetime import datetime, timedelta

from cubie.task.sequence import RequestSequence, TaskStatus

StageStats = dict[str, dict[str, float | int]]

STAGE_ORDER = (
    TaskStatus.PREPROCESSING.value,
    TaskStatus.GPU_SS.value,
    TaskStatus.GPU_SHAPE.value,
    TaskStatus.GPU_MATERIAL.value,
    TaskStatus.EXPORTING.value,
    TaskStatus.UPLOADING.value,
)
PROCESSING_STATUSES = frozenset(
    {
        TaskStatus.PREPROCESSING,
        TaskStatus.GPU_QUEUED,
        TaskStatus.GPU_SS,
        TaskStatus.GPU_SHAPE,
        TaskStatus.GPU_MATERIAL,
        TaskStatus.EXPORTING,
        TaskStatus.UPLOADING,
    }
)


def decorate_sequence_eta(
    sequence: RequestSequence,
    *,
    worker_count: int,
    queue_position: int | None,
    stage_stats: StageStats | None,
    now: datetime,
) -> None:
    if sequence.status == TaskStatus.QUEUED:
        sequence.queue_position = queue_position or None
        sequence.estimated_wait_seconds = estimate_queued_wait(
            stage_stats=stage_stats,
            queue_position=queue_position,
            worker_count=worker_count,
        )
    elif sequence.status in PROCESSING_STATUSES:
        sequence.queue_position = None
        sequence.estimated_wait_seconds = estimate_processing_wait(
            sequence=sequence,
            stage_stats=stage_stats,
        )
    else:
        sequence.queue_position = None
        sequence.estimated_wait_seconds = None

    sequence.estimated_finish_at = (
        now + timedelta(seconds=sequence.estimated_wait_seconds)
        if sequence.estimated_wait_seconds is not None
        else None
    )


def estimate_queued_wait(
    *,
    stage_stats: StageStats | None,
    queue_position: int | None,
    worker_count: int,
) -> int | None:
    if queue_position is None or queue_position <= 0:
        return None
    total_seconds = sum_stage_means(stage_stats, STAGE_ORDER)
    if total_seconds is None:
        return None
    waves = math.ceil(queue_position / max(worker_count, 1))
    return int(math.ceil(waves * total_seconds))


def estimate_processing_wait(
    *,
    sequence: RequestSequence,
    stage_stats: StageStats | None,
) -> int | None:
    current_stage = (sequence.current_stage or sequence.status.value).strip().lower()
    if current_stage == TaskStatus.GPU_QUEUED.value:
        remaining = sum_stage_means(stage_stats, STAGE_ORDER[1:])
        return int(math.ceil(remaining)) if remaining is not None else None
    if current_stage not in STAGE_ORDER:
        return None
    current_mean = stage_mean(stage_stats, current_stage)
    if current_mean is None:
        return None
    current_index = STAGE_ORDER.index(current_stage)
    remaining = sum_stage_means(stage_stats, STAGE_ORDER[current_index + 1 :])
    if remaining is None and current_index + 1 < len(STAGE_ORDER):
        return None
    progress_ratio = min(max(sequence.progress, 0), 100) / 100
    seconds = (current_mean * max(0.0, 1.0 - progress_ratio)) + (remaining or 0.0)
    return int(math.ceil(seconds))


def stage_mean(stage_stats: StageStats | None, stage: str) -> float | None:
    if not stage_stats:
        return None
    stats = stage_stats.get(stage)
    if not stats:
        return None
    if int(stats.get("count", 0)) <= 0:
        return None
    return float(stats.get("mean_seconds", 0.0))


def sum_stage_means(stage_stats: StageStats | None, stages: tuple[str, ...]) -> float | None:
    total = 0.0
    for stage in stages:
        mean = stage_mean(stage_stats, stage)
        if mean is None:
            return None
        total += mean
    return total
