from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from cubie.api.routers.admin_dashboard import build_admin_dashboard_router
from cubie.api.routers.admin_deps import build_admin_deps_router
from cubie.api.routers.admin_gpu import build_admin_gpu_router
from cubie.api.routers.admin_hf import build_admin_hf_router
from cubie.api.routers.admin_keys import build_admin_keys_router
from cubie.api.routers.admin_models import build_admin_models_router
from cubie.api.routers.admin_settings import build_admin_settings_router
from cubie.api.routers.admin_storage import build_admin_storage_router
from cubie.api.routers.admin_tasks import build_admin_tasks_router
from cubie.api.routers.health import build_health_router
from cubie.api.routers.metrics import build_metrics_router
from cubie.api.routers.public_models import build_public_models_router
from cubie.api.routers.spa import build_spa_router, mount_spa_static
from cubie.api.routers.tasks import build_tasks_router
from cubie.api.routers.upload import build_upload_router

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def include_api_routers(app: FastAPI, container: AppContainer) -> None:
    app.include_router(build_health_router(container))
    app.include_router(build_metrics_router(container))
    app.include_router(build_admin_keys_router(container))
    app.include_router(build_upload_router(container))
    app.include_router(build_public_models_router(container))
    app.include_router(build_tasks_router(container))
    app.include_router(build_admin_tasks_router(container))
    app.include_router(build_admin_dashboard_router(container))
    app.include_router(build_admin_gpu_router(container))
    app.include_router(build_admin_models_router(container))
    app.include_router(build_admin_deps_router(container))
    app.include_router(build_admin_storage_router(container))
    app.include_router(build_admin_hf_router(container))
    app.include_router(build_admin_settings_router(container))
    app.include_router(build_spa_router(container))
    mount_spa_static(app)
