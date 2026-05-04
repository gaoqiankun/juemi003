# Project Snapshot

Last updated: 2026-05-04

## Overview

Cubie — self-hostable open-source 3D generation service (image → GLB). FastAPI backend + React frontend, Provider pattern for multi-model switching.

Core flow: `POST /v1/upload` → `POST /v1/tasks` → Worker claim → Stage pipeline (Preprocess → GPU → Export) → Artifact storage → SSE/Webhook notification.

**v0.2 domain-driven refactor (May 2026, completed)**: Restructured monolithic packages into 8 domain-organized packages (core/, task/, vram/, model/, artifact/, auth/, settings/, stage/), eliminating scattered dependencies and improving maintainability. **Stages A–D cleanup (May 3–4)**: (A) extracted 3 misplaced helpers from api/ to correct locations; (B) split api/helpers/deps.py into HTTP layer + model logic; (C) relocated GPU scheduler/subprocess from stage/ to model/, resolving model↔stage entanglement; (D) refactored api/server.py from 2551 → 257 lines using APIRouter pattern across 25 router modules. All stages maintain 221+ passed tests, ruff 7 pre-existing C901 errors.

Test baseline: 221 passed. Production: Docker + uvicorn. Test env: https://gen3d.frps.zhifouai.com

## Package Organization (v0.2)

### `core/` — Shared Infrastructure
Config (ServingConfig, Pydantic BaseSettings), pagination (cursor/page/limit normalization), security (Bearer token validation, rate limiting, URL safety), observability (logging, metrics), GPU device detection (`gpu.py`), HuggingFace utilities (`hf.py`).

### `task/` — Async Task Orchestration
- `engine.py` (437 lines): AsyncGen3DEngine, task lifecycle orchestration
- `eta.py`: ETA calculation from historical stage_stats
- `events.py`: Event queue, task status updates
- `webhook.py`: Webhook dispatch (3 retries)
- `pipeline.py` (455 lines): PipelineCoordinator, task queue (max 20), state machine coordination
- `sequence.py`: RequestSequence dataclass + TaskStatus enum
- `store/`: 6 modules (schema, codec, mutations, queries, analytics) for SQLite persistence; **cursor leak fixed** (concurrent write safety)

State machine: `QUEUED → PREPROCESSING → GPU_QUEUED → GPU_SS → GPU_SHAPE → GPU_MATERIAL → EXPORTING → UPLOADING → SUCCEEDED`. Crash recovery: QUEUED/PREPROCESSING → re-enqueue; GPU+ → force FAILED.

### `vram/` — GPU Memory Management
Three-entity system:
- `allocator.py` (1026 lines): VRAMAllocator arbiter, `request_weight()` / `request_inference()` / `correct_weight()`, asyncio.Lock-protected atomic ops, baseline calibration probe (5s)
- `probe.py`: NVML-based free VRAM sampling
- `helpers.py`: Inference VRAM clamping, device capacity detection

Supports cross-device weight migration, inference lease timeout (5s/2s internal/external), OOM self-healing.

### `model/` — Model Lifecycle & Providers
- `registry.py` (429 lines): ModelWorker container, load/unload/evict lifecycle
- `scheduler.py` (321 lines): Loading policy, LRU tick tracking, per-slot quota enforcement
- `worker.py` (518 lines): Per-model state (allocation, busy flag, evicting flag), GPU subprocess management, run_inference() with OOM recovery
- `weight.py` (836 lines): Weight sourcing (HuggingFace/URL/Local), dependency tracking, archive extraction, progress reporting
- `store.py` (719 lines): Model registry persistence, VRAM measurements (EMA + DB), download state tracking
- `dep_store.py` (458 lines): Dependency instance storage, requirement tracking
- `dep_paths.py` (new, Stage B): Dependency path resolution, moved from api/helpers/deps.py
- `gpu_scheduler.py` (new, Stage C): GPU slot scheduling, moved from stage/gpu/scheduler.py (renamed from scheduler.py to avoid task/scheduler.py collision)
- `gpu_subprocess.py` (new, Stage C): GPU worker subprocess lifecycle, moved from stage/gpu/worker.py (renamed from worker.py to avoid model/worker.py collision)
- `providers/`: Trellis2 / HunYuan3D-2 / Step1X-3D (implementations inherit BaseModelProvider, each with mock + real modes)
- `runtime.py`: Provider factory + build_provider()

### `artifact/` — Asset Storage & Management
- `store.py`: Unified artifact I/O (Local + MinIO backends)
- `manifest.py`: SQLite manifest tracking, atomic delete + rebuild
- `types.py`: ArtifactRecord dataclass
- `utils.py`: Temp path management, content-type detection
- `object_client.py`: S3-compatible client abstraction
- `backends/local.py` + `backends/minio.py`: Backend implementations

Strategy: filesystem + manifest (avoids S3 URL expiry, enables atomic ops).

### `auth/` — Authentication & API Keys
- `api_key_store.py`: Static Bearer token persistence, rate limiting per key
- `helpers.py`: API key validation, hashing, store selection

### `settings/` — Configuration Persistence
- `store.py`: Server settings (max_loaded_models, gpu_disabled_devices, tasks_per_slot)

### `stage/` — Pipeline Stages
Three-stage processing (renamed from `stages/`, May 2026):
1. **PreprocessStage** (317 lines): Download/validate image, format conversion
2. **GPUStage** (671 lines): GPU slot allocation, worker process mgmt, provider invocation (removed external VRAM migration logic → delegated to ModelWorker)
3. **ExportStage** (784 lines): GLB post-processing, preview PNG rendering (PreviewRendererService subprocess), artifact storage

Chosen over single function: independent crash recovery granularity, stage_stats timing for ETA, failed_stage field for error localization.

## AppContainer

Dependency container in `api/server.py::create_app()`, injected into all routes via closure. Contains 17 objects: config, all_device_ids, disabled_devices, task_store, api_key_store, rate_limiter, artifact_store, preview_renderer_service, model_registry, pipeline, engine, model_store, dep_instance_store, model_dep_requirements_store, settings_store, vram_allocator, model_scheduler, weight_manager, model_download_tasks. Routes not split in server.py itself; now instantiated per-router via closure builder pattern.

## API Structure (Stage D Complete)

**server.py**: Refactored from 2551 → 257 lines. Core responsibilities:
- AppContainer dataclass (17 fields)
- VramEstimateDecision + update_vram_estimate / persist_vram_estimate_measurement (lifespan utility)
- create_app() factory: container construction, router registration, middleware setup, lifespan

**routers/** (25 files, 12 groups organized by business domain):
- **Infrastructure**: health.py (3 routes: /health, /readiness, /ready), metrics.py (Prometheus), spa.py (/, /static/*)
- **Public API**: upload.py (/v1/upload), tasks.py (/v1/tasks + SSE), public_models.py (/v1/models)
- **Admin Models**: admin_models.py (CRUD), admin_model_handlers.py (helper), admin_model_create.py (specialized), admin_model_downloads.py
- **Admin Config**: admin_deps.py, admin_keys.py, admin_hf.py, admin_settings.py
- **Admin Ops**: admin_storage.py, admin_tasks.py, admin_gpu.py, admin_dashboard.py
- **Dev**: dev_proxy.py (dev-only request forwarding), auth.py (helper)

**app_components.py** (217L): build_app_components() factory — instantiates all 17 container objects from config.
**app_lifecycle.py** (109L): initialize_app_container() + close_app_container() — startup/shutdown logic for model registry, task engine, preview renderer.

Routers use closure builder pattern: each file exports `build_X_router(container) -> APIRouter`, container injected via closure. No Depends(get_container) pattern. Tests use existing `TestClient(create_app(...))` model.

## Testing Structure (v0.2)

`tests/` mirrored to domain subdirectories: `api/`, `auth/`, `model/`, `settings/`, `stage/`, `task/`, `vram/`. Redundant `sys.path.insert` hacks removed (root `conftest.py` is sole source of truth). 221 tests passed.

Kept at root: `conftest.py` (pytest setup), `inference_lease_test_utils.py` (shared), `test_cross_store_concurrency.py` (integration).

## Code Quality

- **Pre-refactor (April 2026)**: 398 ruff errors
- **Post-stages A–D (May 4 2026)**: 7 errors (all pre-existing C901)
  - `vram/allocator.py` × 2 (1026L monolith, internal split needed)
  - `model/weight.py` × 1
  - `scripts/migrate_missing_deps.py` × 1 (one-off migration tool)
  - `api/routers/admin_settings_update.py` × 1 (admin settings state machine)
  - `api/app_components.py` × 1 (container construction)

Vendor exclusions (updated May 2026): `model/providers/{trellis2,step1x3d}/ext/` (CUDA extensions) + `model/providers/hunyuan3d/pipeline/` (vendor fork).

## Import Dependency Status (Post-Stages A–D)

✅ **Zero reverse dependencies**: all 8 domain packages (vram/, model/, core/, task/, stage/, artifact/, auth/, settings/) → api/ (expected, api is client layer). Previously stage C–D had model↔stage bidirectional deps, now resolved (model/gpu_scheduler, gpu_subprocess corrected). Stage A–B eliminated api-layer leakage from core/model/vram. Top-level import validation baseline: `grep "from cubie.api" cubie/{vram,model,core,task,stage,artifact,auth,settings}` returns empty.

## Refactoring History (May 2026)

Series of 4 cleanup stages (A–D), completed May 3–4:

- **Stage A (May 3)**: Extract misplaced helpers from api/helpers/ → gpu_device.py to core/gpu.py, hf.py to core/hf.py, preflight.py to top level. 3 git mv, 5 files 8 import sites. Tests pass, ruff stable.
- **Stage B (May 3)**: Split api/helpers/deps.py → model/dep_paths.py (path resolution) + api/helpers/deps.py (HTTP error handling). 3 function migration, zero reverse deps. Tests pass, ruff stable.
- **Stage C (May 3)**: Relocate GPU scheduler/subprocess from stage/gpu/ → model/ with rename (gpu_scheduler.py, gpu_subprocess.py) to avoid naming collisions. 2 git mv, 22 import sites, model→stage deps eliminated. Tests pass, ruff stable.
- **Stage D (May 3–4)**: Refactor api/server.py (2551L) → APIRouter pattern across 25 router files + app_components.py + app_lifecycle.py. 6 commits, each with passing tests. server.py 257L target achieved; 35 visible API paths; tests 221+125 passed.

All stages complete, tests 221+ passing, imports verified, zero new ruff violations.
