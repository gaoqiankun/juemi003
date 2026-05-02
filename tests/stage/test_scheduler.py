from __future__ import annotations

from gen3d.stage.gpu.scheduler import FlowMatchingScheduler


def test_scheduler_collects_waiting_items_in_order() -> None:
    scheduler = FlowMatchingScheduler[str]()
    scheduler.enqueue("task-1")
    scheduler.enqueue("task-2")

    assert scheduler.size() == 2
    assert scheduler.drain() == ["task-1", "task-2"]
    assert scheduler.size() == 0
