from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


_logger = structlog.get_logger(__name__)


async def run_model_weight_download(
    container: AppContainer,
    *,
    model_id: str,
    provider_type: str,
    weight_source: str,
    model_path: str,
    dep_assignments: dict[str, dict] | None = None,
) -> None:
    try:
        await container.weight_manager.download(
            model_id=model_id,
            provider_type=provider_type,
            weight_source=weight_source,
            model_path=model_path,
            dep_assignments=dep_assignments,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _logger.warning(
            "model.weight_download_failed",
            model_id=model_id,
            provider_type=provider_type,
            weight_source=weight_source,
            error=str(exc),
        )
    finally:
        current_task = asyncio.current_task()
        if (
            current_task is not None
            and container.model_download_tasks.get(model_id) is current_task
        ):
            container.model_download_tasks.pop(model_id, None)


async def cancel_model_download_task(
    container: AppContainer,
    model_id: str,
) -> None:
    task = container.model_download_tasks.pop(model_id, None)
    if task is None:
        return
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
