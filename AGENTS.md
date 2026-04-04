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
- If a change affects another module's behavior, prepend a note to `.ai/decisions.md`
- Log any friction to `.ai/friction-log.md`
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

## Toolchain

> ⛔ All Python commands MUST go through `uv run`. Never use `.venv/bin/python`, `python`, `pip`, `source .venv/bin/activate`, or any direct venv activation.

```bash
uv run python -m pytest tests -q   # tests (baseline: ≥ 163 passed)
uv run ruff check .                # lint (no new issues)
uv run python <script.py>          # run script
cd web && npm run build            # frontend (zero errors required)
```
