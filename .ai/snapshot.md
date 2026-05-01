# Project Snapshot

Last updated: 2026-05-01

## Overview

Cubie — self-hostable open-source 3D generation service (image → GLB). FastAPI backend + React frontend, Provider pattern for multi-model switching.

Core flow: `POST /v1/upload` → `POST /v1/tasks` → Worker claim → Stage pipeline (Preprocess → GPU → Export) → Artifact storage → SSE/Webhook notification.

Main components: API layer (server.py, 2571 lines, 43 routes), async engine (engine/), stage pipeline (stages/), model providers (model/), storage layer (storage/, 5 stores), React SPA (web/), admin panel with System page for GPU/Storage management.

Test baseline: 220 passed. Production: Docker + uvicorn. Test env: https://gen3d.frps.zhifouai.com

## AppContainer

Dependency container constructed by `create_app()` in `api/server.py`, injected into all routes via closure capture. Contains 16 objects: config, task_store, api_key_store, rate_limiter, artifact_store, preview_renderer_service, model_registry, pipeline, engine, model_store, dep_cache_store, model_dep_requirements_store, settings_store, model_scheduler, weight_manager, model_download_tasks.

Routes are not split (v0.2 plans Router factory pattern refactor) — splitting now requires DI framework, not worth the complexity.

## Task Engine

`engine/async_engine.py` (400 lines) orchestrates task execution. Already modularized: ETA calculation (async_engine_eta.py), event queue (async_engine_events.py), webhook dispatch (async_engine_webhook.py, 3 retries).

`engine/pipeline.py` `PipelineCoordinator` manages task queue (max 20) and stage orchestration. Task timeout: 3600s.

State machine: `QUEUED → PREPROCESSING → GPU_QUEUED → GPU_SS → GPU_SHAPE → GPU_MATERIAL → EXPORTING → UPLOADING → SUCCEEDED`. Any state → `FAILED / CANCELLED`.

Crash recovery: QUEUED/PREPROCESSING → re-enqueue; GPU+ → force FAILED (GPU results unrecoverable).

## VRAM Management

Three-entity architecture implemented (April 2026):

**VRAMAllocator** (`engine/vram_allocator.py`, 39,877 bytes) — centralized VRAM arbiter:
- Manages weight allocations (model weights on GPU devices) and inference allocations (temporary VRAM for inference)
- `request_weight(model_id, mb) → WeightAllocation` — searches devices with space or idle candidates for eviction; raises `VRAMInsufficientError` if all full
- `request_inference(model_id, device_id, inference_mb) → InferenceAllocation` — 5s wait window for same-device allocation; falls back to cross-device migration
- `correct_weight(allocation_id, actual_mb)` — updates weight measurements after GPU worker reports
- `register_worker / unregister_worker` — tracks model workers for eviction candidate selection
- `asyncio.Lock` spans entire check→evict→record cycle (prevents concurrent double-eviction)
- External baseline calibration probe loop (every 5s) refines free VRAM estimates from NVML
- Deprecated wrappers: `reserve() / release() / acquire_inference()` delegate to new ledger

**ModelWorker** (`engine/model_worker.py`, 17,865 bytes) — model lifecycle management:
- Per-model worker manages load/unload/evict; holds weight allocation and GPU subprocess
- Three state flags: `_weight_allocated` (weight reserved), `_inference_busy` (inference in flight), `_evicting` (shutting down)
- `load() / unload() / evict()` — weight allocation + GPU subprocess lifecycle
- `run_inference()` — OOM self-healing: on CUDA OOM, re-request from allocator (cross-device migration if needed)
- Measurements: weight_vram_mb (model+weights), inference_vram_mb (peak inference) — both EMA-updated and persisted to DB
- Implements `ModelWorkerInterface` Protocol for allocator eviction callbacks

**ModelScheduler** (`engine/model_scheduler.py`, 11,209 bytes) — simplified to loading policy:
- No longer makes eviction decisions (moved to VRAMAllocator)
- `on_task_queued()` → calls `model_registry.load(worker)` if not loaded
- `on_task_completed() / on_model_loaded()` → updates LRU tick and per-slot task quota
- Max loaded models enforced by allocator space constraint, not scheduler hardcap

## Model System

### Registry & Worker Container

`engine/model_registry.py` (14,822 bytes) — now a `ModelWorker` container:
- `_entries[model_id]` holds `_ModelEntry(worker=ModelWorker(...))`
- `load()` → creates/returns `ModelWorker`, calls `worker.load()` async
- `unload()` → calls `worker.evict()` or `worker.unload()`
- `get_runtime()` → returns `ModelRuntime` (for GPUStage scheduler/worker access), backed by worker's GPU subprocess
- Lazy-loads with 30-min timeout; lifecycle driven by `ModelWorker`

### Weight Manager

`engine/weight_manager.py` (30,817 bytes) unified management of three weight sources: HuggingFace Hub / URL / Local. 
- `model_definitions` extended with 6 tracking fields: weight_source, download_status, download_progress, download_speed_bps, download_error, resolved_path
- Falls back to `model_path` when `resolved_path` is empty
- Provider dependency tracking (dinov2, depth-anything, face-detection-yolov8) with lifecycle management
- Supports archive extraction (zip/tar.gz) and progress reporting

### Providers

Three providers, all implementing mock + real modes, inheriting `BaseModelProvider` (ABC) from `model/base.py`:

| Provider | Directory | Purpose |
|----------|-----------|---------|
| Trellis2 | model/trellis2/ | image-to-3D |
| HunYuan3D-2 | model/hunyuan3d/ | shape + texture (includes FaceReducer preprocessing) |
| Step1X-3D | model/step1x3d/ | 3D generation |

Provider interface: `dependencies() → from_pretrained() → run_batch() → export_glb()`. `Hunyuan3D-2/` directory is untracked — expected.

## Stage Pipeline

Three-stage pipeline, each stage async with `on_update` callback for status updates:

1. **PreprocessStage** (stages/preprocess/, 317 lines) — download/validate image, format conversion
2. **GPUStage** (stages/gpu/, 671 lines) — GPU slot allocation (GPUSlotScheduler) + worker process management (GPUWorkerHandle) + provider invocation; removed external VRAM migration logic (now handled by ModelWorker)
3. **ExportStage** (stages/export/, 784 lines) — GLB post-processing + preview PNG rendering (PreviewRendererService subprocess) + artifact storage

Stage pipeline chosen over single function: different crash recovery granularity, independent stage_stats timing for ETA estimation, `failed_stage` field returned to client for error localization.

## Storage Layer

| Store | Files | Purpose |
|-------|-------|---------|
| TaskStore | storage/task_store*.py (5 files) | SQLite task persistence, queries, analytics; **cursor leak fixed** (concurrent write safety) |
| ArtifactStore | storage/artifact_*.py (5 files) | Unified artifact I/O, Local + MinIO backends |
| ModelStore | storage/model_store.py (715 lines) | Model registry + download state tracking + VRAM measurements |
| ApiKeyStore | storage/api_key_store.py (379 lines) | API key management + rate limiting |
| SettingsStore | storage/settings_store.py (103 lines) | Server settings (max_loaded_models, gpu_disabled_devices, tasks_per_slot) |
| DepStore | storage/dep_store.py (283 lines) | Model dependency tracking + VRAM measurements |

Artifact uses filesystem + manifest over pure S3 presigned URLs: avoids URL expiry, atomic delete, manifest self-heals on rebuild.

**Cursor leak fixes** (April 2026): All stores now properly isolate cursor lifecycle; concurrent read/write ops no longer trigger SQLITE_LOCKED. Cross-store testing validates concurrent behavior.

## Auth

Static Bearer token (`secrets.compare_digest` for timing-attack resistance), no JWT. Sufficient for private deployment.

## Configuration

`config.py` (229 lines) Pydantic BaseSettings, env-var driven. Key settings: provider_mode (mock/real), gpu_device_ids, queue_max_size (20), rate_limit_concurrent (5), rate_limit_per_hour (100), task_timeout_seconds (3600).

New settings (April 2026): `gpu_disabled_devices` (list of device IDs to exclude from allocation), `external_vram_wait_timeout_seconds` (5s), `internal_vram_wait_timeout_seconds` (2s).

## Frontend

React SPA structure: app/ (routes), components/, pages/, hooks/, i18n/, lib/, styles/.

User pages: Setup → Generate (upload/generate/SSE progress/preview) → Gallery → Viewer (3D view/download/delete).

Admin panel: Tasks (monitoring) / Models (register/load/unload toggle) / **System** (new, April 2026) / API Keys / Settings.

**System Page** (new April 2026):
- GPU Devices section: list devices (label, name, totalMemoryGb), toggle enable/disable with immediate effect (no save button)
- Storage section: disk usage bar, cache/orphaned stats, cleanup orphaned with confirmation dialog (shows size + count)
- VRAM Monitor panel: real-time weight/inference allocations per device, EMA measurements, external baseline estimates

## API Structure

`api/server.py` (2571 lines) — core routes, DI container, 43 endpoints:
- Upload / task creation / status / result / cancel
- Model management (register, load, unload, delete, weights)
- Settings (read/update)
- Admin (GPU devices, storage, VRAM snapshot, API keys)
- Development proxy for local model serving

`api/helpers/` (10 files) — extracted module-level helpers (May 2026 refactor):
- `runtime.py` — device ID validation
- `keys.py` — API key validation + hashing
- `hf.py` — HuggingFace repo ID detection
- `tasks.py` — error formatting, status mapping
- `artifacts.py` — artifact path/download headers
- `vram.py` — VRAM estimate clamping
- `gpu_device.py` — device info + ID resolution
- `deps.py` — dependency resolution
- Plus: `security.py` (Bearer token extraction), `prefixes.py` (path prefix helpers)

## Naming & Code Quality

May 2026 refactor: Removed `_` prefixes from ~171 module-level helper functions across storage/, engine/, api/helpers/, and config modules. Updated cross-file imports (14 files) to use public names. Tests (220 passed) synchronized with updated function names.
