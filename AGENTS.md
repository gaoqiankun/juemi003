# Cubie · Agent Spec

> Read `~/AGENTS.md` (global workflow) first, then this file (project constraints), then the role file specified in the prompt (`.ai/roles/[slug].md` if exists, otherwise `~/dotai/roles/[domain]/[slug].md`).

## Project Overview

**Cubie** — open-source 3D generation service (image → GLB). FastAPI backend + React frontend.

```
gen3d/
├── config.py / serve.py   # backend entrypoints
├── api/                   # FastAPI routes and schemas
├── engine/                # task engine
├── model/                 # Provider implementations (trellis2 / hunyuan3d / step1x3d)
├── stages/                # preprocess / gpu / export
├── storage/               # 5 stores (SQLite + filesystem)
├── tests/                 # baseline: 163 passed
├── web/                   # React SPA
├── .claude/               # Claude Code: rules/ + skills/
└── .ai/                # agent workspace: roles/ + plan/ + docs
```

## Rules

- Do not modify `ios/`, `server/`, `Hunyuan3D-2/`
- Plan files are created by Orchestrator — Worker reads only, never writes; on completion write report to `.ai/tmp/report-{task}.md`
- If a change affects another module's behavior, prepend a note to `.ai/decisions.md`
- Log any friction (missing docs, wrong paths, unclear flow) to `.ai/friction-log.md`
- Do not upgrade dependencies unless explicitly asked

## Python Toolchain

Always use `uv` for Python:

```bash
uv run python -m pytest tests -q   # run tests (baseline: ≥ 163 passed)
uv run ruff check .                # lint (no new issues allowed)
uv run python <script.py>          # run script
```

## Frontend

```bash
cd web && npm run build            # zero errors required
```
