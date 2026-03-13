from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.stages.gpu.scheduler import FlowMatchingScheduler


def test_scheduler_collects_waiting_items_in_order() -> None:
    scheduler = FlowMatchingScheduler[str]()
    scheduler.enqueue("task-1")
    scheduler.enqueue("task-2")

    assert scheduler.size() == 2
    assert scheduler.drain() == ["task-1", "task-2"]
    assert scheduler.size() == 0
