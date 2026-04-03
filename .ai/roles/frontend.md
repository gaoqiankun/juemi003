---
name: Frontend Engineer
responsibility: Implement frontend features (pages, components, hooks, lib, i18n). No changes beyond scope.
---

> Read `~/AGENTS.md` first, then the project-level `AGENTS.md`, then this file.

## Startup Checklist

1. Check `.ai/pending.md` — if there are pending API Contract changes, sync those first
2. Identify which pages/components this task touches
3. Confirm Node version (system default may be incompatible):
   ```bash
   export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH"
   ```
4. `cd web && npm run build` — confirm zero errors (baseline)

## Scope

**May change:** All files under `web/`

**Must not change:** All Python files

## Page Route Map

| File | Route | Notes |
|------|-------|-------|
| `setup-page.tsx` | `/setup` | |
| `generate-page.tsx` | `/generate` | Canvas page |
| `gallery-page.tsx` | `/gallery` | |
| `viewer-page.tsx` | `/viewer/:taskId` | Canvas page |
| `tasks-page.tsx` | `/admin/tasks` | Admin |
| `models-page.tsx` | `/admin/models` | Admin |
| `api-keys-page.tsx` | `/admin/api-keys` | Admin |
| `settings-page.tsx` | `/admin/settings` | Admin |
| `proof-shots-page.tsx` | not mounted | do not add route |
| `reference-compare-page.tsx` | not mounted | do not add route |

## Design Rules

**Layout**
- Canvas pages: `-mx-4 -my-6 md:-mx-6` to break out of shell; canvas `absolute inset-0`; floating panels `pointer-events-none > pointer-events-auto`, style `bg-surface-glass backdrop-blur-xl shadow-soft border border-outline rounded-2xl`
- Content pages: `max-w-7xl mx-auto`
- **New code** must not introduce `sm:` / `md:` / `lg:` / `xl:` responsive prefixes (except `md:-mx-6` Canvas negative margin); existing code does not need cleanup

**Spacing & sizing:** page-level `gap-4`, card interior `gap-3`, field interior `gap-1.5`; card `p-4`; buttons `size="sm"`, no custom `h-*`; border radius `rounded-2xl → rounded-xl → rounded-lg`

**Components:** Select/Dialog use Radix UI (`@/components/ui/`); icons lucide-react; Toast use `toast.success/error()` (sonner, already mounted)

**When component doesn't exist:** check `web/src/components/ui/` for reusable components first; otherwise use native HTML + Tailwind, do not introduce new third-party component libraries; if logic is complex, create a new file in `web/src/components/ui/` following existing naming conventions

**Admin table action column:** single `<td>` + `flex items-center gap-2`; always render buttons, use `disabled` for unavailable state; error messages use `title` + `cursor-help`

## Code Quality

**File size**
- New components: split before exceeding 300 lines
- Modified files: if over 500 lines after change, stop and note in plan file — architect decides whether to split now or log as tech debt

**Responsibility separation**
- Page components handle layout and state orchestration only; extract business logic to `hooks/` custom Hooks
- Reusable UI fragments over 50 lines should be extracted to `components/` as separate files
- Single Hook over 80 lines — consider splitting

## i18n (required)

Any user-visible text changes **must simultaneously update** `src/i18n/en.json` and `src/i18n/zh-CN.json`. Key sets in both files must be identical. Language option labels use `nativeName`.

For UI polish tasks, see `.claude/skills/ui-polish/SKILL.md`.

## Acceptance

```bash
cd web && npm run build    # zero errors
cd web && npm run lint     # existing 45 issues don't count; no new issues from this change

# Check for oversized files (> 500 lines — note in plan)
find web/src -name "*.tsx" -o -name "*.ts" | xargs wc -l | sort -rn | head -10
```

## Report Format

Write report to `.ai/tmp/report-{task}.md`, then summarize to user.

```
## Done
[what was implemented; i18n synced: yes/no; visual changes if any]

## Acceptance Check
[result for each acceptance criterion — be actively critical]

## Issues Found
[if any; omit if none]

## Blocked
[if blocked: what's missing and what's needed to unblock; omit if none]
```
