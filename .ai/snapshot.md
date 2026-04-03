# Project Snapshot

Last updated: 2026-04-04

## Overview

Cubie — self-hostable open-source 3D generation service (image → GLB). FastAPI backend + React frontend, Provider pattern for multi-model switching.

Core flow: `POST /v1/upload` → `POST /v1/tasks` → Worker claim → Stage pipeline (Preprocess → GPU → Export) → Artifact storage → SSE/Webhook notification.

Main components: API layer (server.py, 2571 lines, 43 routes), async engine (engine/), stage pipeline (stages/), model providers (model/), storage layer (storage/, 5 stores), React SPA (web/).

Test baseline: 163 passed. Production: Docker + uvicorn. Test env: https://gen3d.frps.zhifouai.com

## AppContainer

Dependency container constructed by `create_app()` in `api/server.py`, injected into all routes via closure capture. Contains 16 objects: config, task_store, api_key_store, rate_limiter, artifact_store, preview_renderer_service, model_registry, pipeline, engine, model_store, dep_cache_store, model_dep_requirements_store, settings_store, model_scheduler, weight_manager, model_download_tasks.

Routes are not split (v0.2 plans Router factory pattern refactor) — splitting now requires DI framework, not worth the complexity.

## Task Engine

`engine/async_engine.py` (400 lines) orchestrates task execution. Already modularized: ETA calculation (async_engine_eta.py), event queue (async_engine_events.py), webhook dispatch (async_engine_webhook.py, 3 retries).

`engine/pipeline.py` `PipelineCoordinator` manages task queue (max 20) and stage orchestration. Task timeout: 3600s.

State machine: `QUEUED → PREPROCESSING → GPU_QUEUED → GPU_SS → GPU_SHAPE → GPU_MATERIAL → EXPORTING → UPLOADING → SUCCEEDED`. Any state → `FAILED / CANCELLED`.

Crash recovery: QUEUED/PREPROCESSING → re-enqueue; GPU+ → force FAILED (GPU results unrecoverable).

## Model System

### Registry & Scheduler

`engine/model_registry.py` (250 lines) lazy-loads models with async event coordination, 30-min timeout. `engine/model_scheduler.py` (428 lines) manages model lifecycle (load/unload) based on task queue and settings. LRU + max_tasks_per_slot quota prevents cold model starvation.

### Weight Manager

`engine/weight_manager.py` (594 lines) unified management of three weight sources: HuggingFace Hub / URL / Local. `model_definitions` extended with 6 tracking fields (weight_source, download_status, download_progress, download_speed_bps, download_error, resolved_path). Falls back to `model_path` when `resolved_path` is empty.

### Providers

Three providers, all implementing mock + real modes, inheriting `BaseModelProvider` (ABC) from `model/base.py`:

| Provider | Directory | Purpose |
|----------|-----------|---------|
| Trellis2 | model/trellis2/ | image-to-3D |
| HunYuan3D-2 | model/hunyuan3d/ | shape + texture |
| Step1X-3D | model/step1x3d/ | 3D generation |

Provider interface: `dependencies()` → `from_pretrained()` → `run_batch()` → `export_glb()`. `Hunyuan3D-2/` directory is untracked — expected.

## Stage Pipeline

Three-stage pipeline, each stage async with `on_update` callback for status updates:

1. **PreprocessStage** (stages/preprocess/, 317 lines) — download/validate image, format conversion
2. **GPUStage** (stages/gpu/, 671 lines) — GPU slot allocation (GPUSlotScheduler) + worker process management (GPUWorkerHandle) + provider invocation
3. **ExportStage** (stages/export/, 784 lines) — GLB post-processing + preview PNG rendering (PreviewRendererService subprocess) + artifact storage

Stage pipeline chosen over single function: different crash recovery granularity, independent stage_stats timing for ETA estimation, `failed_stage` field returned to client for error localization.

## Storage Layer

| Store | Files | Purpose |
|-------|-------|---------|
| TaskStore | storage/task_store*.py (5 files) | SQLite task persistence, queries, analytics |
| ArtifactStore | storage/artifact_*.py (5 files) | Unified artifact I/O, Local + MinIO backends |
| ModelStore | storage/model_store.py (561 lines) | Model registry + download state tracking |
| ApiKeyStore | storage/api_key_store.py (379 lines) | API key management + rate limiting |
| SettingsStore | storage/settings_store.py (103 lines) | Server settings (max_loaded_models, tasks_per_slot) |
| DepStore | storage/dep_store.py (283 lines) | Model dependency tracking |

Artifact uses filesystem + manifest over pure S3 presigned URLs: avoids URL expiry, atomic delete, manifest self-heals on rebuild.

## Auth

Static Bearer token (`secrets.compare_digest` for timing-attack resistance), no JWT. Sufficient for private deployment.

## Configuration

`config.py` (229 lines) Pydantic BaseSettings, env-var driven. Key settings: provider_mode (mock/real), gpu_device_ids, queue_max_size (20), rate_limit_concurrent (5), rate_limit_per_hour (100), task_timeout_seconds (3600).

## Frontend

React SPA structure: app/ (routes), components/, pages/, hooks/, i18n/, lib/, styles/.

User pages: Setup → Generate (upload/generate/SSE progress/preview) → Gallery → Viewer (3D view/download/delete).

Admin panel: Tasks (monitoring) / Models (register/load/start-stop) / API Keys / Settings.
