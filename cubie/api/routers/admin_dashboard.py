from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from cubie.api.helpers.auth import build_require_admin_token
from cubie.api.helpers.tasks import map_task_status
from cubie.auth.helpers import build_user_key_label_map, resolve_task_owner

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_admin_dashboard_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.get(
        "/api/admin/dashboard",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_dashboard() -> dict:
        task_counts = await container.task_store.count_tasks_by_status()
        recent = await container.task_store.get_recent_tasks(limit=10)
        throughput = await container.task_store.get_throughput_stats(hours=1)
        active = await container.task_store.get_active_task_count()
        key_label_map = await build_user_key_label_map(container.api_key_store)

        stats = [
            {"key": "activeTasks", "value": active, "change": ""},
            {
                "key": "queued",
                "value": task_counts.get("queued", 0) + task_counts.get("gpu_queued", 0),
                "change": "",
            },
            {"key": "completed", "value": task_counts.get("succeeded", 0), "change": ""},
            {"key": "failed", "value": task_counts.get("failed", 0), "change": ""},
        ]

        gpu = {
            "model": "N/A",
            "utilization": 0,
            "vramUsedGb": 0,
            "vramTotalGb": 0,
            "temperatureC": 0,
            "powerW": 0,
            "fanPercent": 0,
            "cudaVersion": "",
            "driverVersion": "",
            "activeJobs": active,
            "avgLatencySeconds": throughput.get("avg_duration_seconds") or 0,
        }

        recent_tasks = []
        for task in recent:
            task_key_id = str(task.get("key_id") or "")
            owner, key_label = resolve_task_owner(task_key_id, key_label_map)
            recent_tasks.append(
                {
                    "id": task["id"],
                    "subjectKey": "",
                    "model": task.get("model", ""),
                    "status": map_task_status(task["status"]),
                    "durationSeconds": 0,
                    "createdAt": task.get("created_at", ""),
                    "owner": owner,
                    "keyId": task_key_id,
                    "keyLabel": key_label,
                }
            )

        return {
            "stats": stats,
            "gpu": gpu,
            "recentTasks": recent_tasks,
            "nodes": [],
            "workers": [],
        }

    return router
