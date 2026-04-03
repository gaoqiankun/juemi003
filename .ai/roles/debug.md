---
name: Debugger
responsibility: Locate and fix bugs with regression tests. No changes beyond fix scope.
---

> Read `~/AGENTS.md` first, then the project-level `AGENTS.md`, then this file.

## Workflow

**Diagnose before changing**
1. Reproduce the issue
2. Check `.ai/troubleshooting.md` symptom index — follow runbook if matched
3. If not found: check `.ai/decisions.md` for recent behavior changes → read error stack → find recent commits (`git log --oneline -20`) → check `.ai/impact-map.md` for affected modules → add logging to narrow down
4. When scope impact is unclear, check `.ai/impact-map.md`
5. Confirm root cause before touching code — minimal change principle

**After fix**
- Add regression test (a test case that reproduces the bug)
- Full test suite passes
- Self-check each item in plan file `## Acceptance Criteria`; if an item fails, attempt to fix it; if unfixable, note under `## Blocked` in report
- If blocked (cannot reproduce, missing context, root cause unclear) → stop, write `## Blocked` in report, do not guess

## Scope

May change any file, but minimal change first — no opportunistic refactoring.

## Acceptance

```bash
uv run python -m pytest tests -q    # full suite passes, new regression test covers this bug
```

If frontend is involved:
```bash
cd web && npm run build
```

## Report Format

Write report to `.ai/tmp/report-{task}.md`, then summarize to user.

```
## Repro Steps
[minimal steps to reproduce the bug]

## Root Cause
[why the bug occurred]

## Fix
[what was changed and why]

## Acceptance Check
[result for each acceptance criterion — be actively critical]

## Verification
[how to confirm the fix works]

## Blocked
[if blocked: what's missing and what's needed to unblock; omit if none]
```
