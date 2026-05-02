# Project Snapshot

Last updated: 2026-05-03

## Overview

Cubie — self-hostable open-source 3D generation service (image → GLB). FastAPI backend + React frontend, Provider pattern for multi-model switching.

Core flow: `POST /v1/upload` → `POST /v1/tasks` → Worker claim → Stage pipeline (Preprocess → GPU → Export) → Artifact storage → SSE/Webhook notification.

**v0.2 domain-driven refactor (May 2026)**: Restructured monolithic packages into 8 domain-organized packages (core/, task/, vram/, model/, artifact/, auth/, settings/, stage/), eliminating scattered dependencies and improving maintainability. Main entry point `api/server.py` (2550 lines, 43 routes) remains the controller; domain packages encapsulate business logic with clear boundaries.

Test baseline: 221 passed. Production: Docker + uvicorn. Test env: https://gen3d.frps.zhifouai.com

## Package Organization (v0.2)

### `core/` — Shared Infrastructure
Config (ServingConfig, Pydantic BaseSettings), pagination (cursor/page/limit normalization), security (Bearer token validation, rate limiting, URL safety), observability (logging, metrics).

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

Dependency container in `api/server.py::create_app()`, injected into all routes via closure. Contains 16 objects: config, task_store, api_key_store, rate_limiter, artifact_store, preview_renderer_service, model_registry, pipeline, engine, model_store, dep_cache_store, model_dep_requirements_store, settings_store, model_scheduler, weight_manager, model_download_tasks.

Routes not split (v0.2 plans Router factory refactor after domain refactor stabilizes).

## API Structure

`api/server.py` (2550 lines) — 43 endpoints:
- Upload / task creation / status / result / cancel
- Model management (register, load, unload, delete, weights)
- Settings (read/update)
- Admin (GPU devices, storage, VRAM snapshot, API keys)
- Development proxy for local model serving

`api/helpers/` (10 files) — extracted helpers:
- `runtime.py` — provider factory
- `keys.py` — API key validation + hashing (will be in auth/ post-stage-3b)
- `hf.py` — HuggingFace repo ID detection
- `tasks.py` — error formatting, status mapping
- `artifacts.py` — artifact path/download headers
- `vram.py` — VRAM estimate clamping
- `gpu_device.py` — device info + ID resolution
- `deps.py` — dependency resolution (stays in api/ per stage 3b decision: mixing API errors + model logic)
- `security.py` (Bearer token), `prefixes.py` (path prefix helpers)

## Testing Structure (v0.2)

`tests/` mirrored to domain subdirectories: `api/`, `auth/`, `model/`, `settings/`, `stage/`, `task/`, `vram/`. Redundant `sys.path.insert` hacks removed (root `conftest.py` is sole source of truth). 221 tests passed.

Kept at root: `conftest.py` (pytest setup), `inference_lease_test_utils.py` (shared), `test_cross_store_concurrency.py` (integration).

## Code Quality

- **Pre-refactor (April 2026)**: 398 ruff errors
- **Post-refactor (May 2026)**: 7 errors (all pre-existing C901)
  - `api/server.py` × 3 (monolith awaiting router refactor)
  - `vram/allocator.py` × 2 (1026L monolith awaiting internal split)
  - `model/weight.py` × 1
  - `scripts/migrate_missing_deps.py` × 1 (one-off migration tool)

Vendor exclusions (updated May 2026): `model/providers/{trellis2,step1x3d}/ext/` (CUDA extensions) + `model/providers/hunyuan3d/pipeline/` (vendor fork).

## Refactoring History (May 2026)

Series of 9 domain-refactor commits (stages 0–7), each focusing on moving files from monolithic structure into organized packages:

- **Stage 0**: Establish `core/` package (config, pagination, security, observability)
- **Stage 1**: Establish `task/` package (async_engine, pipeline, sequence, task_store)
- **Stage 2**: Establish `vram/` package (vram_allocator, vram_probe, helpers)
- **Stage 3a**: Move model lifecycle into `model/` (registry, scheduler, worker, weight, store, dep_store)
- **Stage 3b**: Move providers to `model/providers/`, runtime to `model/runtime.py`
- **Stage 4**: Build `artifact/`, `auth/`, `settings/` packages; remove `storage/`
- **Stage 5**: Rename `stages/` → `stage/` (singular)
- **Stage 6**: Mirror `tests/` to domain subdirectories, remove redundant sys.path hacks
- **Stage 7**: Fix ruff exclude paths, autofix migration script

All stages complete, tests passing, imports verified.
