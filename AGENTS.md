# Cubie · Agent Spec

> Read `~/AGENTS.md` (global workflow) first, then this file, then the role file specified in the prompt (`.ai/roles/[slug].md` if exists, otherwise `~/dotai/roles/[domain]/[slug].md`).

## Project Overview

**Cubie** — self-hostable open-source 3D generation service (image → GLB). FastAPI backend + React frontend, Provider pattern for multi-model switching, SQLite + filesystem storage.

Test environment: https://gen3d.frps.zhifouai.com

See `.ai/snapshot.md` for detailed architecture and module status.

Architecture: **API → Engine (async worker) → Stage Pipeline → Provider**

- `config.py` / `serve.py` — backend entrypoints
- `api/server.py` — all routes + AppContainer (11 objects, closure-captured)
- `engine/` — async_engine / pipeline / model_registry / model_scheduler
- `model/` — Provider implementations (Trellis2, HunYuan3D-2, Step1X-3D; all mock + real ready)
- `stages/` — preprocess / gpu / export
- `storage/` — 5 stores (SQLite + filesystem)
- `web/src/` — React SPA

Key design decisions:
- Stage pipeline over single function — different crash recovery granularity, independent stage_stats timing, `failed_stage` returned to client
- All routes in server.py — AppContainer closure capture, splitting needs DI; v0.2 refactor
- Artifact filesystem + manifest — avoids presigned URL expiry, atomic delete, manifest self-heals
- LRU + max_tasks_per_slot — pure LRU starves cold models; quota enables fair scheduling
- Static Bearer token — private deploy, `secrets.compare_digest` sufficient

Task state machine:
```
QUEUED → PREPROCESSING → GPU_QUEUED → GPU_SS → GPU_SHAPE → GPU_MATERIAL
       → EXPORTING → UPLOADING → SUCCEEDED
Any → FAILED / CANCELLED
```

Crash recovery: QUEUED/PREPROCESSING → re-enqueue; GPU+ → force FAILED.

## Environments

| Environment | Machine | Purpose |
|-------------|---------|---------|
| Dev | Mac or lab (Ubuntu) | Code, tests, AI agents (Orchestrator + Worker) |
| Deploy | GPU machine (separate) | Docker, actual model inference |

- Orchestrator and Worker both run on dev machines — may be Mac or lab, tooling varies
- Dev machines are isolated from the deploy machine unless the user explicitly says otherwise
- Code reaches deploy via git / rsync (tool not fixed)
- GPU-dependent model calls require the deploy machine — use mocks on dev
- Worker prompt `Working directory:` must use the project directory name (`gen3d/`), not an absolute path

## Rules

- Do not modify `ios/`, `server/`, `Hunyuan3D-2/`
- `Hunyuan3D-2/` directory is untracked in git — expected
- Plan files are created by Orchestrator — Worker reads only, never writes; on completion write report to `.ai/tmp/report-{task}.md`
- If a change affects another module's behavior, prepend a note to `.ai/decisions.md`
- Log any friction to `.ai/friction-log.md`
- Do not upgrade dependencies unless explicitly asked

## Toolchain

> ⛔ All Python commands MUST go through `uv run`. Never use `.venv/bin/python`, `python`, `pip`, `source .venv/bin/activate`, or any direct venv activation.

```bash
uv run python -m pytest tests -q   # tests (baseline: ≥ 163 passed)
uv run ruff check .                # lint (no new issues)
uv run python <script.py>          # run script
cd web && npm run build            # frontend (zero errors required)
```
