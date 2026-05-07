# Project Snapshot

Last updated: 2026-05-07

## Overview

Cubie — self-hostable open-source 3D generation service (image → GLB). FastAPI backend + React frontend, Provider pattern for multi-model switching.

Core flow: `POST /v1/upload` → `POST /v1/tasks` → Worker claim → Stage pipeline (Preprocess → GPU → Export) → Artifact storage → SSE/Webhook notification.

**v0.2 domain-driven refactor + stages A–U complete (May 3–6, 2026)**: Restructured monolithic packages into 8 domain-organized packages; eliminated circular dependencies; split 9 remaining monoliths (worker.py, registry.py, dep_store.py, api_key_store.py, pipeline.py, engine.py, allocator.py) into subpackages using Mixin pattern; reduced C901 violations 7→0; fixed pre-existing allocator-registry desynchronization bug. 

Test baseline: 223 passed (221 baseline + 2 new allocator-registry sync tests). Production: Docker + uvicorn. Test env: https://gen3d.frps.zhifouai.com

## Package Organization (v0.2 Complete)

### `core/` — Shared Infrastructure
Config (ServingConfig, Pydantic BaseSettings), pagination (cursor/page/limit normalization), security (Bearer token validation, rate limiting, URL safety), observability (logging, metrics), GPU device detection (`gpu.py`), HuggingFace utilities (`hf.py`).

### `task/` — Async Task Orchestration
- **`engine/` (6 Mixin: May 6)**: AsyncGen3DEngine split from 442L monolith. Mixins: `LifecycleMixin` (start/stop), `TasksMixin` (submit/list/cancel), `WorkerLoopMixin` (claim/load), `CleanupMixin` (garbage collect), `PrewarmMixin` (startup preload). All 17 instance attrs declared in main `__init__`.
- **`pipeline/` (5 Mixin: May 5)**: PipelineCoordinator split from 456L monolith. Mixins: `LifecycleMixin`, `ExecutionMixin`, `GPUStageMixin`, `PublishMixin`, `RecoveryMixin`. All instance attrs in main `__init__`. OOM recovery + GPU stage scheduling fully preserved.
- **`store/` (6 modules)**: SQLite persistence; cursor leak fixed (concurrent write safety)
- Other: `eta.py` (ETA calculation), `events.py` (Event queue), `webhook.py` (Webhook dispatch, 3 retries), `sequence.py` (RequestSequence + TaskStatus)

State machine: `QUEUED → PREPROCESSING → GPU_QUEUED → GPU_SS → GPU_SHAPE → GPU_MATERIAL → EXPORTING → UPLOADING → SUCCEEDED`. Crash recovery: QUEUED/PREPROCESSING → re-enqueue; GPU+ → force FAILED.

### `vram/` — GPU Memory Management
**`allocator/` (8 Mixin: May 6)**: VRAMAllocator split from 1026L (largest file). 7 Mixin pattern: `ConfigMixin`, `WeightMixin`, `InferenceMixin`, `BookingMixin`, `EvictionMixin`, `ProbeMixin`, `MetricsMixin`. All 25+ instance attrs in main `__init__`. 

**C901 fixes (Stage Q)**: `request_inference` (C15→≤10), `apply_external_baselines` (C11→≤10) via helper extraction. VRAM allocation, eviction, and migration logic fully preserved.

**Bug fix (Stage U)**: Fixed pre-existing allocator-registry desynchronization introduced in VRAM management overhaul (`c204aac`). When `evict_worker` evicted a candidate, registry entry became stale (state="ready" but worker._runtime=None). Solution: (1) Listener pattern — `allocator.add_eviction_listener(registry.on_external_eviction)` notifies registry post-eviction; (2) Guard in `wait_ready` — detects stale entry (`weight_allocated=False` while state="ready"), resets entry and retriggers load instead of raising RuntimeError.

Other modules: `probe.py` (NVML-based free VRAM sampling), `helpers.py` (Inference VRAM clamping, device capacity detection).

### `model/` — Model Lifecycle & Providers
**Recent splits (May 5–6)**:
- **`worker/` (5 Mixin: May 5)**: ModelWorker split from 518L. Mixins: `LifecycleMixin` (load/evict/unload), `InferenceMixin` (run_batch + `run_inference` backward-compat alias), `VRAMEstimateMixin` (VRAM tracking + OOM recovery). All 12 instance attrs in main `__init__`. EMA coefficients (0.7/0.3), OOM bump (1.5x), weight estimation (max(int(round(total*0.75)), 1)) fully preserved.
- **`registry/` (5 Mixin: May 5)**: ModelRegistry split from 429L. Mixins: `LifecycleMixin` (load/reload/unload), `QueriesMixin` (state/runtime queries), `ListenersMixin` (model_loaded/unloaded/weight_measured). Core state: `_entries` dict (state machine: not_loaded/loading/ready/error/unloading), `_lock` (asyncio.Lock).
- **`dep_store/` (5 files: May 5)**: DepInstanceStore + ModelDepRequirementsStore split from 458L monolith. Composition pattern: `__init__.py` defines base + classes, submodules (instance_queries, instance_mutations, normalize, migrations) share `_db/_lock` via store reference.
- **`gpu/` (4 files)**: GPU worker abstraction, lifecycle mgmt, child process entry, message serialization
- **`weight/` (5 files)**: Weight sourcing (HuggingFace/URL/Local), dependency tracking, archive extraction
- **`store/` (5 files)**: Model registry persistence (VRAM measurements, download state tracking)
- **`providers/`**: Trellis2 / HunYuan3D-2 / Step1X-3D (implementations, mock + real modes)
- Other: `scheduler.py` (loading policy, LRU), `factory.py` (provider runtime factory), `types.py` (ModelRuntime / ModelRegistryLoadError), `errors.py` (friendly_model_error_message + provider error facade), `dep_paths.py` (dependency path resolution)

### `auth/` — Authentication & API Keys
**`api_key_store/` (6 files: May 5)**: ApiKeyStore split from 379L monolith. Composition pattern: `__init__.py` (facade), `queries.py` (read paths), `mutations.py` (write paths with lock), `normalize.py` (serialization), `migrations.py` (schema), `constants.py` (USER_KEY_SCOPE/METRICS_SCOPE). Static Bearer token persistence, rate limiting per key.

Other: `helpers.py` (API key validation, hashing, store selection)

### `settings/` — Configuration Persistence
- `store.py`: Server settings (max_loaded_models, gpu_disabled_devices, tasks_per_slot)

### `stage/` — Pipeline Stages
Three-stage processing (renamed from `stages/`, May 2026):
1. **PreprocessStage** (317 lines): Download/validate image, format conversion
2. **GPUStage** (671 lines): GPU slot allocation, worker process mgmt, provider invocation
3. **ExportStage** (784 lines): GLB post-processing, preview PNG rendering, artifact storage

### `artifact/` — Asset Storage & Management
- `store.py`: Unified artifact I/O (Local + MinIO backends)
- `manifest.py`: SQLite manifest tracking, atomic delete + rebuild
- `types.py`: ArtifactRecord dataclass
- `utils.py`: Temp path management, content-type detection
- `object_client.py`: S3-compatible client abstraction
- `backends/`: local.py + minio.py (Backend implementations)

Strategy: filesystem + manifest (avoids S3 URL expiry, enables atomic ops).

## AppContainer

Dependency container in `api/server.py::create_app()`, injected into all routes via closure. Contains 17 objects: config, all_device_ids, disabled_devices, task_store, api_key_store, rate_limiter, artifact_store, preview_renderer_service, model_registry, pipeline, engine, model_store, dep_instance_store, model_dep_requirements_store, settings_store, vram_allocator, model_scheduler, weight_manager. Routes instantiated per-router via closure builder pattern.

## API Structure (Complete)

**server.py**: Refactored from 2551 → 257 lines. Core responsibilities:
- AppContainer dataclass (17 fields)
- VramEstimateDecision + VRAM estimate utilities
- create_app() factory: container construction, router registration, middleware setup, lifespan

**routers/** (Complete reorg): 13 root-level files + 3 subpackages organized by business domain:
- **Infrastructure**: health.py (3 routes: /health, /readiness, /ready), metrics.py (Prometheus), spa.py (/, /static/*)
- **Public API**: upload.py (/v1/upload), tasks/ (/v1/tasks + SSE), public_models.py (/v1/models)
- **Admin Models**: admin/models/ (4 files)
- **Admin Config**: admin/settings/ (3 files + update.py with C901 fix), admin_deps.py, admin_hf.py, admin_keys.py
- **Admin Ops**: admin_storage.py, admin_gpu.py, admin_dashboard.py, admin_tasks.py
- **Dev**: dev_proxy.py (dev-only request forwarding), helpers/auth.py (API token validators)

**preflight.py**: Moved to `cubie/api/preflight.py`; initialization sanity checks; dead code removed.

**app_components.py** (217L): build_app_components() factory instantiates all 17 container objects.
**app_lifecycle.py** (109L): initialize_app_container() + close_app_container() — startup/shutdown logic.

## Structure Polish V1-V6 (May 6-7, 2026)

### Facade Boundaries (P0a-P0e consolidation)

- 8 domain facades now keep explicit `__all__`: `core`, `task`, `vram`, `model`, `stage`, `artifact`, `auth`, `settings`
- Cross-domain callers use facade-first imports by default (provider implementation paths remain explicit)
- Deep imports are constrained to whitelisted cases:
  - `cubie.model.providers.*` (lazy provider loading policy)
  - facade re-export locations (`cubie/<domain>/__init__.py`)
  - test fixture/module alias imports
  - same-domain sibling imports needed by package init ordering
  - intentional internal/private deep paths (`artifact` internals, registry private symbols, GPU subsystem via `cubie.model.gpu` / `cubie.model.worker`)
- Subpackage `__init__.py` exports were tightened: mixins remain internal; only stable public types/functions are exported

### Naming and File Layout Corrections

- Admin routers flattened into domain packages: `api/routers/admin/<name>/__init__.py` replaces legacy `admin_<name>.py`
- `model/gpu_scheduler.py` moved to `model/gpu/scheduler.py`
- `stage/gpu/stage.py` and `stage/preprocess/stage.py` flattened to `stage/gpu_stage.py` and `stage/preprocess_stage.py`
- Runtime naming fixed: `model/runtime.py` renamed to `model/factory.py`; runtime dataclass moved to `model/types.py`
- Error/helper placement fixed: `friendly_model_error_message` migrated to `model/errors.py`
- Logger naming fixed: `vram/helpers.py` now logs under `cubie.vram.helpers`
- Artifact store factory ownership clarified: `build_artifact_store` is colocated in `api/app_components.py`; `api/helpers/artifacts.py` focuses on preview rendering helpers

### Dead Code and Compatibility Cleanup

- `model/registry/compat.py` dead compatibility branches were removed after caller audit
- Registry foundational types/helpers were moved out of compat naming into durable type modules (`model/types.py`, registry-local modules)

### V1-V6 to P-Item Mapping

| Stage | P items covered | Key outputs |
|---|---|---|
| V1 | P1, P2, P3 (+P0a/P0d partial) | admin route package move, GPU scheduler rename, stage flattening, initial stage facade imports |
| V2 | P4, P8(partial), P7 (+P0a/P0d partial) | `model/types.py` extraction, circular import cleanup, vram logger naming fix |
| V3 | P5 (+P0a partial) | registry/compat audit + dead path cleanup, model facade strengthening |
| V4 | P6 (+P0a partial) | `friendly_model_error_message` moved to `model/errors.py`, task helper scope narrowed |
| V5 | P9, P8(completed) (+P0a partial) | `runtime.py` → `factory.py`, runtime type ownership finalized |
| V6.1/V6.2 | P0a/P0b/P0d/P0e major sweep | facade `__all__` expansion, cross-domain import rewrite, subpackage export tightening |
| V6.3 | P11 + V6 closure docs | artifact factory migration to app components, snapshot alignment, final verification/reporting |

## Testing Structure (v0.2)

`tests/` mirrored to domain subdirectories: api/, auth/, model/, settings/, stage/, task/, vram/. Root `conftest.py` is sole source of truth for sys.path. 223 tests passed (includes 2 new allocator-registry sync tests from Stage U).

## Code Quality

- **Pre-stages A–J (April 2026)**: 398 ruff errors
- **Post-stages K–U (May 6 2026)**: **0 C901 errors** (all eliminated)
  - Stage R: update_settings C901 (36→≤10) via 9 field validators
  - Stage S: migrate_missing_deps C901 (13→≤10) via 2 helpers
  - Stage Q: allocator C901 (C15 request_inference + C11 apply_external_baselines → ≤10 each) via helper extraction
  - All 9 monolith splits (K–P) + setattr cleanup (T) = 0 new violations

Vendor exclusions (updated May 2026): `model/providers/{trellis2,step1x3d}/ext/` (CUDA extensions) + `model/providers/hunyuan3d/pipeline/` (vendor fork).

## Import Dependency Status (Post-Stages K–U)

✅ **Zero reverse dependencies**: all 8 domain packages → api/ (expected, api is client layer). All monolith splits preserved public API with 0 external import changes:
- Stage K `dep_store.py` → `cubie/model/dep_store/`: 6 sites unchanged
- Stage L `worker.py` → `cubie/model/worker/`: 6 sites unchanged (including test monkeypatch paths audited per Stage J lesson)
- Stage M `registry.py` → `cubie/model/registry/`: 13 sites unchanged (14 imports including ModelRuntime + error type)
- Stage N `api_key_store.py` → `cubie/auth/api_key_store/`: 6 sites unchanged (including constants re-export)
- Stage O `pipeline.py` → `cubie/task/pipeline/`: 4 sites unchanged
- Stage P `engine.py` → `cubie/task/engine/`: 4 sites unchanged (3 app-level + 1 test)
- Stage Q `allocator.py` → `cubie/vram/allocator/`: 13 sites unchanged (all public names re-exported)

Top-level import validation baseline: `grep "from cubie.api" cubie/{vram,model,core,task,stage,artifact,auth,settings}` returns empty.

## Refactoring History (May 2026)

Series of 21 cleanup stages (A–U), completed May 3–6:

**Initial Cleanup (Stages A–J, May 3–5)**: Extracted helpers, split API, reorganized routers, eliminated 2 monoliths (weight.py, store.py, gpu_subprocess.py).

**Monolith Split Batch (Stages K–P, May 5)**: Split 6 large files using Mixin pattern:
- **K** (May 5): dep_store.py (458L) → dep_store/ (5 files, max 180L). Composition pattern with shared `_SQLiteStore` base.
- **L** (May 5): worker.py (518L) → worker/ (5 Mixin files, max 191L). Complex state access (12 attrs across 4 slices) → Mixin inheritance. EMA/OOM logic preserved.
- **M** (May 5): registry.py (429L) → registry/ (5 Mixin files, max 186L). State machine (not_loaded/loading/ready/error/unloading) fully preserved.
- **N** (May 5): api_key_store.py (379L) → api_key_store/ (6 files, max 160L). Composition pattern; constants re-exported.
- **O** (May 5): pipeline.py (456L) → pipeline/ (5 Mixin files, max 112L). OOM recovery + GPU scheduling logic intact.
- **P** (May 5): engine.py (442L) → engine/ (6 Mixin files, max 198L). 17 instance attrs, worker loop scheduling intact.

**Giant Allocator Split + C901 Fixes (Stage Q, May 6)**: allocator.py (1026L, largest file) → allocator/ (8 Mixin files, max 299L, plus InferenceLease). Simultaneous C901 fix: `request_inference` (C15→≤10), `apply_external_baselines` (C11→≤10) via helpers. VRAM allocation/eviction/migration logic 100% preserved; outcome strings & EMA coefficients identical.

**C901 Fixes (Stages R–S, May 5–6)**:
- **R** (May 5): update_settings C901 (36→≤10) via 9 field validators (defaultProvider, queueMaxSize, maxLoadedModels, maxTasksPerSlot, externalVramWaitTimeoutSeconds, internalVramWaitTimeoutSeconds, gpuDisabledDevices, rateLimitPerHour, rateLimitConcurrent). 422 error strings identical.
- **S** (May 5): migrate_missing_deps C901 (13→≤10) via `_resolve_or_create_instance` + `_ensure_dep_instances_table` helpers. stdout format unchanged.

**Cleanup (Stages T–U, May 6)**:
- **T** (May 6): Pipeline/lifecycle.py setattr workaround cleanup. 2 lines: `setattr(self, "_started", v)` → `self._started = v` (proper Python attribute mutation, not grep-evading).
- **U** (May 6): Fix allocator-registry desynchronization bug (pre-existing, from VRAM management overhaul `c204aac`). Root cause: `evict_worker` directly evicts candidate without notifying registry, leaving stale `state="ready"` entries. Fix: (1) Listener pattern — allocator notifies registry post-eviction; (2) wait_ready guard — detects stale entries via `weight_allocated=False`, resets entry and retriggers load. 2 new tests + no behavior change.

All stages complete, tests 223 passed, imports verified, all C901 violations resolved.
