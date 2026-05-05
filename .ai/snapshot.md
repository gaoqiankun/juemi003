# Project Snapshot

Last updated: 2026-05-05

## Overview

Cubie — self-hostable open-source 3D generation service (image → GLB). FastAPI backend + React frontend, Provider pattern for multi-model switching.

Core flow: `POST /v1/upload` → `POST /v1/tasks` → Worker claim → Stage pipeline (Preprocess → GPU → Export) → Artifact storage → SSE/Webhook notification.

**v0.2 domain-driven refactor + stages A–J cleanup (May 2026, completed)**: Restructured monolithic packages into 8 domain-organized packages (core/, task/, vram/, model/, artifact/, auth/, settings/, stage/), eliminating scattered dependencies and improving maintainability. **Stages A–D cleanup (May 3–4)**: (A) extracted 3 misplaced helpers from api/ to correct locations; (B) split api/helpers/deps.py into HTTP layer + model logic; (C) relocated GPU scheduler/subprocess from stage/ to model/, resolving model↔stage entanglement; (D) refactored api/server.py from 2551 → 257 lines using APIRouter pattern across 25 router modules. **Stages E–J (May 4–5)**: (E) reorganized `routers/` 25 flat files → 3 subpackages (admin/models/, admin/settings/, tasks/) + relocated 2 non-router files (auth.py → helpers/auth.py, dev_proxy.py → api/dev_proxy.py); (F) moved preflight.py → api/preflight.py + deleted dead validate_runtime_security_config(); (H,I,J) split 3 large monoliths (weight.py 836L, store.py 719L, gpu_subprocess.py 623L) into subpackages (weight/, store/, gpu/) with single-file sizes ≤300L. All stages maintain 221+ passed tests, ruff C901 violations reduced from 7 → 5.

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
**Stage J (May 5) split gpu_subprocess.py → gpu/ subpackage:**
- `gpu/` (4 files, ≤300L each): GPU worker abstraction, lifecycle mgmt, child process entry, message serialization. Public API (`AsyncGPUWorker`, `ProcessGPUWorker`, `GPUWorkerHandle`, `build_gpu_workers`) preserved; 11 import sites (scheduler, runtime, tests) updated from `gpu_subprocess` → `gpu`.
- `gpu_scheduler.py`: GPU slot scheduling, moved from stage/ (Stage C)
- Other key files:
  - `registry.py` (429 lines): ModelWorker container, load/unload/evict lifecycle
  - `scheduler.py` (321 lines): Loading policy, LRU tick tracking, per-slot quota enforcement
  - `worker.py` (518 lines): Per-model state (allocation, busy flag, evicting flag), GPU subprocess management, run_inference() with OOM recovery
  - `weight/` (5 files, ≤300L: Stage H split): Weight sourcing (HuggingFace/URL/Local), dependency tracking, archive extraction, progress reporting. Modules: `__init__.py` (WeightManager main), `downloader.py`, `deps.py`, `archive.py`, `storage_scan.py`. Public API unchanged.
  - `store/` (5 files, ≤300L: Stage I split): Model registry persistence. Modules: `__init__.py` (ModelStore main), `queries.py`, `mutations.py`, `normalize.py`, `migrations.py`. VRAM measurements (EMA + DB), download state tracking. Public API unchanged.
  - `dep_store.py` (458 lines): Dependency instance storage, requirement tracking
  - `dep_paths.py`: Dependency path resolution, moved from api/helpers/deps.py (Stage B)
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

## API Structure (Stages D + E Complete)

**server.py**: Refactored from 2551 → 257 lines. Core responsibilities:
- AppContainer dataclass (17 fields)
- VramEstimateDecision + update_vram_estimate / persist_vram_estimate_measurement (lifespan utility)
- create_app() factory: container construction, router registration, middleware setup, lifespan

**routers/** (Stage E reorganized): 13 root-level files + 3 subpackages (admin/, tasks/) organized by business domain:
- **Infrastructure**: health.py (3 routes: /health, /readiness, /ready), metrics.py (Prometheus), spa.py (/, /static/*)
- **Public API**: upload.py (/v1/upload), tasks/ (/v1/tasks + SSE), public_models.py (/v1/models)
- **Admin Models**: admin/models/ (4 files: __init__, create, downloads, handlers)
- **Admin Config**: admin/settings/ (3 files: __init__, get, update), admin_deps.py, admin_hf.py, admin_keys.py
- **Admin Ops**: admin_storage.py, admin_gpu.py, admin_dashboard.py, admin_tasks.py
- **Dev**: dev_proxy.py (dev-only request forwarding at top-level api/), helpers/auth.py (API token validators, moved Stage E)

**preflight.py** (Stage F): Moved to `cubie/api/preflight.py`; initialization sanity checks (artifact_store, model_store, trellis2 runtime detection); dead code `validate_runtime_security_config()` removed.

**app_components.py** (217L): build_app_components() factory — instantiates all 17 container objects from config.
**app_lifecycle.py** (109L): initialize_app_container() + close_app_container() — startup/shutdown logic for model registry, task engine, preview renderer.

Routers use closure builder pattern: each file exports `build_X_router(container) -> APIRouter`, container injected via closure. No Depends(get_container) pattern. Tests use existing `TestClient(create_app(...))` model.

## Testing Structure (v0.2)

`tests/` mirrored to domain subdirectories: `api/`, `auth/`, `model/`, `settings/`, `stage/`, `task/`, `vram/`. Redundant `sys.path.insert` hacks removed (root `conftest.py` is sole source of truth). 221 tests passed.

Kept at root: `conftest.py` (pytest setup), `inference_lease_test_utils.py` (shared), `test_cross_store_concurrency.py` (integration).

## Code Quality

- **Pre-refactor (April 2026)**: 398 ruff errors
- **Post-stages A–J (May 5 2026)**: 5 errors (all pre-existing C901)
  - `vram/allocator.py` × 1 (1026L monolith, internal split needed)
  - `model/weight/deps.py` × 1 (inherited from original weight.py)
  - `model/weight/downloader.py` × 1 (inherited from original weight.py)
  - `scripts/migrate_missing_deps.py` × 1 (one-off migration tool)
  - `api/routers/admin_settings_update.py` × 1 (admin settings state machine, now in admin/settings/update.py)

Stages H/I/J eliminated weight.py and store.py C901 violations; gpu_subprocess.py split achieved <300L per file with zero new violations.

Vendor exclusions (updated May 2026): `model/providers/{trellis2,step1x3d}/ext/` (CUDA extensions) + `model/providers/hunyuan3d/pipeline/` (vendor fork).

## Import Dependency Status (Post-Stages A–J)

✅ **Zero reverse dependencies**: all 8 domain packages (vram/, model/, core/, task/, stage/, artifact/, auth/, settings/) → api/ (expected, api is client layer). Stage J updated 11 import sites for gpu_subprocess → gpu; Stages H/I preserved public API with 0 external changes. Top-level import validation baseline: `grep "from cubie.api" cubie/{vram,model,core,task,stage,artifact,auth,settings}` returns empty. `grep cubie.api.routers cubie/{vram,model,core,task,stage,artifact,auth,settings}` returns empty.

## Refactoring History (May 2026)

Series of 10 cleanup stages (A–J), completed May 3–5:

- **Stage A (May 3)**: Extract misplaced helpers from api/helpers/ → gpu_device.py to core/gpu.py, hf.py to core/hf.py, preflight.py to top level. 3 git mv, 5 files 8 import sites. Tests pass, ruff stable.
- **Stage B (May 3)**: Split api/helpers/deps.py → model/dep_paths.py (path resolution) + api/helpers/deps.py (HTTP error handling). 3 function migration, zero reverse deps. Tests pass, ruff stable.
- **Stage C (May 3)**: Relocate GPU scheduler/subprocess from stage/gpu/ → model/ with rename (gpu_scheduler.py, gpu_subprocess.py) to avoid naming collisions. 2 git mv, 22 import sites, model→stage deps eliminated. Tests pass, ruff stable.
- **Stage D (May 3–4)**: Refactor api/server.py (2551L) → APIRouter pattern across 25 router files + app_components.py + app_lifecycle.py. 6 commits, each with passing tests. server.py 257L target achieved; 35 visible API paths; tests 221+ passing.
- **Stage E (May 4)**: Reorganize routers/ 25 flat → 3 subpackages (admin/models/, admin/settings/, tasks/); relocate auth.py → helpers/auth.py, dev_proxy.py → api/dev_proxy.py. 25 files affected, 13 auth import sites + 1 dev_proxy + 11 subpackage path updates. Tests 221+ passing.
- **Stage F (May 4)**: Move preflight.py → api/preflight.py, delete dead validate_runtime_security_config(). 1 git mv, 3 lines deleted in server.py. Tests 221+ passing.
- **Stage H (May 5)**: Split model/weight.py (836L) → weight/ subpackage (5 files: __init__, downloader, deps, archive, storage_scan), each ≤300L. C901 violations (weight.py) eliminated. 0 external import changes. Tests 221+ passing.
- **Stage I (May 5)**: Split model/store.py (719L) → store/ subpackage (5 files: __init__, queries, mutations, normalize, migrations), each ≤300L. Composition over Mixin for shared state. 0 external import changes. Tests 221+ passing.
- **Stage J (May 5)**: Split model/gpu_subprocess.py (623L) → gpu/ subpackage (4 files: __init__, lifecycle, worker_main, messaging), each ≤300L. 11 import sites updated (scheduler, runtime, 9 tests). Tests 221+ passing.

All stages complete, tests 221+ passing, imports verified, ruff C901 reduced 7→5 across project.

