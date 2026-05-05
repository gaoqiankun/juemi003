from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from cubie.api.helpers.auth import build_require_bearer_token
from cubie.api.schemas import UserModelListResponse, UserModelSummary

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_public_models_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_bearer_token = build_require_bearer_token(container)

    @router.get(
        "/v1/models",
        response_model=UserModelListResponse,
    )
    async def list_enabled_models(
        key_id: str = Depends(require_bearer_token),
    ) -> UserModelListResponse:
        del key_id
        enabled_models = await container.model_store.get_enabled_models(
            extra_statuses=frozenset({"pending"}) if container.config.is_mock_provider else frozenset(),
        )
        runtime_states = container.model_registry.runtime_states()
        return UserModelListResponse(
            models=[
                UserModelSummary(
                    id=str(model["id"]),
                    display_name=str(model["display_name"]),
                    is_default=bool(model["is_default"]),
                    runtime_state=str(
                        runtime_states.get(str(model["id"]).strip().lower(), "not_loaded")
                    ),
                )
                for model in enabled_models
            ]
        )

    return router
