from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from cubie.api.routers.auth import build_require_admin_token
from cubie.core.gpu import get_gpu_device_info

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


def build_admin_gpu_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_admin_token = build_require_admin_token(container)

    @router.get(
        "/api/admin/gpu/state",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_admin_gpu_state() -> dict:
        snapshot_by_device = container.vram_allocator.snapshot()
        runtime_states = container.model_registry.runtime_states()
        holders: list[dict[str, object]] = []
        devices: list[dict[str, object]] = []
        cluster_total_vram_mb = 0
        cluster_reserved_vram_mb = 0
        cluster_used_weight_vram_mb = 0
        cluster_used_inference_vram_mb = 0
        cluster_free_vram_mb = 0
        cluster_effective_free_vram_mb = 0

        for device_id in container.all_device_ids:
            snapshot = snapshot_by_device.get(device_id, {})
            total_vram_mb = int(snapshot.get("total_vram_mb", 0))
            reserved_vram_mb = int(snapshot.get("reserved_vram_mb", 0))
            used_weight_vram_mb = int(snapshot.get("used_weight_vram_mb", 0))
            used_inference_vram_mb = int(snapshot.get("used_inference_vram_mb", 0))
            free_vram_mb = int(snapshot.get("free_vram_mb", 0))
            external_baseline_mb = int(snapshot.get("external_baseline_mb", 0))
            effective_free_vram_mb = max(free_vram_mb - external_baseline_mb, 0)
            allocations = {
                str(model_name).strip().lower(): int(vram_mb)
                for model_name, vram_mb in dict(snapshot.get("allocations", {})).items()
                if str(model_name).strip()
            }
            inference_allocations = {
                str(allocation_id).strip(): int(vram_mb)
                for allocation_id, vram_mb in dict(
                    snapshot.get("inference_allocations", {})
                ).items()
                if str(allocation_id).strip()
            }
            inference_allocation_models = {
                str(allocation_id).strip(): str(model_name).strip().lower()
                for allocation_id, model_name in dict(
                    snapshot.get("inference_allocation_models", {})
                ).items()
                if str(allocation_id).strip()
            }
            external_occupation_mb = max(free_vram_mb - effective_free_vram_mb, 0)

            cluster_total_vram_mb += total_vram_mb
            cluster_reserved_vram_mb += reserved_vram_mb
            cluster_used_weight_vram_mb += used_weight_vram_mb
            cluster_used_inference_vram_mb += used_inference_vram_mb
            cluster_free_vram_mb += free_vram_mb
            cluster_effective_free_vram_mb += effective_free_vram_mb

            for model_name, vram_mb in allocations.items():
                holders.append(
                    {
                        "kind": "weight",
                        "modelName": model_name,
                        "deviceId": device_id,
                        "vramMb": vram_mb,
                        "runtimeState": str(
                            runtime_states.get(model_name, "not_loaded")
                        ),
                    }
                )
            for allocation_id, vram_mb in inference_allocations.items():
                holders.append(
                    {
                        "kind": "inference",
                        "allocationId": allocation_id,
                        "modelName": inference_allocation_models.get(allocation_id, ""),
                        "deviceId": device_id,
                        "vramMb": vram_mb,
                    }
                )

            weight_models = [
                {"name": model_name, "vramMb": vram_mb}
                for model_name, vram_mb in allocations.items()
            ]
            weight_models.sort(
                key=lambda model_item: int(model_item["vramMb"]),
                reverse=True,
            )
            device_info = get_gpu_device_info(device_id)
            devices.append(
                {
                    "deviceId": device_id,
                    "name": str(device_info.get("name") or f"GPU {device_id}"),
                    "totalVramMb": total_vram_mb,
                    "reservedVramMb": reserved_vram_mb,
                    "usedWeightVramMb": used_weight_vram_mb,
                    "usedInferenceVramMb": used_inference_vram_mb,
                    "freeVramMb": free_vram_mb,
                    "effectiveFreeVramMb": effective_free_vram_mb,
                    "externalOccupationMb": external_occupation_mb,
                    "weightModels": weight_models,
                    "inferenceCount": len(inference_allocations),
                    "enabled": device_id not in container.disabled_devices,
                }
            )

        holders.sort(key=lambda holder: int(holder.get("vramMb", 0)), reverse=True)
        return {
            "cluster": {
                "deviceCount": len(container.all_device_ids),
                "totalVramMb": cluster_total_vram_mb,
                "reservedVramMb": cluster_reserved_vram_mb,
                "usedWeightVramMb": cluster_used_weight_vram_mb,
                "usedInferenceVramMb": cluster_used_inference_vram_mb,
                "freeVramMb": cluster_free_vram_mb,
                "effectiveFreeVramMb": cluster_effective_free_vram_mb,
            },
            "holders": holders,
            "devices": devices,
        }

    return router
