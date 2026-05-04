from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from cubie.api.routers.auth import build_require_admin_token
from cubie.api.routers.tasks import get_cursor_pagination_params
from cubie.api.schemas import CursorPaginationParams, TaskListResponse, TaskSummary
from cubie.auth.helpers import build_user_key_label_map, resolve_task_owner

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_admin_tasks_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.get(
        "/api/admin/tasks",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_admin_tasks(
        key_id: str | None = Query(default=None),
        pagination: CursorPaginationParams = Depends(get_cursor_pagination_params),
    ) -> dict:
        page = await container.engine.list_tasks(
            key_id=key_id,
            limit=pagination.limit,
            before=pagination.before,
        )
        response = TaskListResponse(
            items=[TaskSummary.from_sequence(task) for task in page.items],
            has_more=page.has_more,
            next_cursor=page.next_cursor,
        ).model_dump(by_alias=True, mode="json")
        key_label_map = await build_user_key_label_map(container.api_key_store)
        items = response.get("items", [])
        for index, sequence in enumerate(page.items):
            if index >= len(items):
                break
            owner, key_label = resolve_task_owner(sequence.key_id, key_label_map)
            items[index]["keyId"] = str(sequence.key_id or "")
            items[index]["keyLabel"] = key_label
            items[index]["owner"] = owner
        return response

    @router.get(
        "/api/admin/tasks/stats",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_tasks_stats() -> dict:
        counts = await container.task_store.count_tasks_by_status()
        throughput = await container.task_store.get_throughput_stats(hours=1)
        active = await container.task_store.get_active_task_count()

        overview = [
            {
                "key": "throughput",
                "value": throughput.get("completed_count", 0),
                "unit": "/h",
                "change": "",
            },
            {
                "key": "latency",
                "value": throughput.get("avg_duration_seconds") or 0,
                "unit": "s",
                "change": "",
            },
            {"key": "active", "value": active, "change": ""},
        ]
        return {"overview": overview, "countByStatus": counts}

    return router
