# Cubie · Agent Spec

## Project Overview

**Cubie** — self-hostable open-source 3D generation service (image → GLB). FastAPI backend + React frontend, Provider pattern for multi-model switching, SQLite + filesystem storage.

Test environment: https://gen3d.frps.zhifouai.com

Architecture: **API → Engine (async worker) → Stage Pipeline → Provider**. See `.ai/snapshot.md` for module details, state machine, and design decisions.

## Environments

| Environment | Machine | Purpose |
|-------------|---------|---------|
| Dev | Mac or lab (Ubuntu) | Code, tests, AI agents (Orchestrator + Worker) |
| Deploy | GPU machine (separate) | Docker, actual model inference |

- GPU-dependent model calls require the deploy machine — use mocks on dev
- Worker prompt `Working directory:` must use the project directory name (`gen3d/`), not an absolute path

## Scope by Role

| Role | May change | Must not change |
|------|-----------|----------------|
| Backend | All Python files except `web/`, `tests/` | `web/`, `ios/`, `server/`, `Hunyuan3D-2/` |
| Frontend | All files under `web/` | All Python files |
| Debugger | Any file (minimal change only) | — |

**Backend — where to put new things:**

| What | Where |
|------|-------|
| New API route | `api/server.py` (centralized, do not split) |
| New request/response schema | `api/schemas.py` |
| New Provider | `model/<name>/provider.py`, implement `model/base.py` Protocol |
| New Stage | `stages/<name>/stage.py` |
| New storage logic | new store file under `storage/` |

## Rules

- `Hunyuan3D-2/` directory is untracked in git — expected
- Plan files are created by Orchestrator — Worker reads only, never writes; on completion write report to `.ai/tmp/report-{task}.md`
- Worker only writes to `.ai/tmp/`; all persistent `.ai/*.md` files (decisions, friction-log, impact-map, snapshot, etc.) are Orchestrator-owned
- Worker must surface in their report: (a) cross-module behavior changes for `.ai/decisions.md`, (b) friction encountered for `.ai/friction-log.md`
- Orchestrator reads the report during validate and writes these persistent files before commit
- Do not upgrade dependencies unless explicitly asked
- Public API changes must be backward-compatible (new fields: `Optional` + default value)
- No business logic in `config.py` / `serve.py`
- When scope impact is unclear, check `.ai/impact-map.md` before proceeding
- Debugging: check `.ai/troubleshooting.md` symptom index first → `.ai/decisions.md` for recent changes → `git log --oneline -20` → `.ai/impact-map.md`

## Code Quality

- New files: split before exceeding 300 lines, single responsibility per file
- Modified files: if over 500 lines after change, stop and note in plan file — architect decides
- Known oversized file (`api/server.py` ~1900 lines, v0.2 refactor): do not add more code; new routes require architect approval
- Functions/methods over 50 lines — consider extracting

## Frontend Rules

**Layout**
- Canvas pages: `-mx-4 -my-6 md:-mx-6` to break out of shell; canvas `absolute inset-0`; floating panels `pointer-events-none > pointer-events-auto`, style `bg-surface-glass backdrop-blur-xl shadow-soft border border-outline rounded-2xl`
- Content pages: `max-w-7xl mx-auto`
- **New code** must not introduce `sm:` / `md:` / `lg:` / `xl:` responsive prefixes (except `md:-mx-6` Canvas negative margin); existing code does not need cleanup

**Spacing & sizing:** page-level `gap-4`, card interior `gap-3`, field interior `gap-1.5`; card `p-4`; buttons `size="sm"`, no custom `h-*`; border radius `rounded-2xl → rounded-xl → rounded-lg`

**Components:** Select/Dialog use Radix UI (`@/components/ui/`); icons lucide-react; Toast use `toast.success/error()` (sonner, already mounted). When component doesn't exist: check `web/src/components/ui/` first; otherwise native HTML + Tailwind, do not introduce new third-party component libraries

**Admin table action column:** single `<td>` + `flex items-center gap-2`; always render buttons, use `disabled` for unavailable state; error messages use `title` + `cursor-help`

**Structure:** page components handle layout + state only; extract business logic to `hooks/`; reusable UI fragments over 50 lines → `components/`; single Hook over 80 lines → consider splitting

**i18n (required):** any user-visible text changes must simultaneously update `src/i18n/en.json` and `src/i18n/zh-CN.json`. Key sets must be identical

**Routes:** see `App.tsx`. Do NOT add routes for `proof-shots-page.tsx` or `reference-compare-page.tsx`

**Node version:** `export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH"`

## Git Workflow

### Branching

- `main` — 稳定分支，只接受 squash merge
- `dev` — 开发分支，从 `main` 切出，合并后删除
- `archive/<version>` — 版本归档，保留开发完整历史供 debug 追溯
- `archive/fix-<slug>` — fix 归档，统一在 archive/ namespace 下

### Commit 规范

- 每个任务的 plan 文件（status: done）必须和代码在**同一个 commit** 里提交
- 不要把 plan 更新攒到最后集中处理

### Squash Merge 流程

按顺序执行，每步完成后再进入下一步：

1. **确认 dev 上所有工作完成** — 代码、测试、plan 文件都已提交，所有 plan status: done
2. **`dotai snapshot`** — 吸收所有已完成 plan 到 snapshot.md，删除 plan 文件
3. **验证 dev 干净** — 无残留 plan 文件，snapshot 内容正确
4. **提交 snapshot** — `chore: snapshot — absorb all completed plans`
5. **归档开发分支** — `git branch archive/<version> dev`
6. **Squash merge** — `git checkout main && git merge --squash dev && git commit`
7. **删除 dev** — `git branch -D dev`
8. **用户 push** — Orchestrator 不 push

### 注意

- 不要在 squash merge 后再 amend — 所有收尾在 merge 前完成
- 后续新开发从 main 切出新的 dev 分支
- 任何修改都要切分支，不直接在 main 上改

## Toolchain

> ⛔ All Python commands MUST go through `uv run`. Never use `.venv/bin/python`, `python`, `pip`, `source .venv/bin/activate`, or any direct venv activation.

```bash
uv run python -m pytest tests -q   # tests (baseline: ≥ 163 passed)
uv run ruff check .                # lint (no new issues)
uv run python <script.py>          # run script
cd web && npm run build            # frontend (zero errors required)
```
