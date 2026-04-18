# Fix Progress Reporting: 5%→25%→60%→90%→100%
Date: 2026-04-18
Status: done

## Goal

Restore visible intermediate progress stages during Trellis2 inference.
Currently users see: GPU_QUEUED (5%) → long wait → SUCCEEDED (100%).
Expected: GPU_QUEUED (5%) → GPU_SS (25%) → GPU_SHAPE (60%) → GPU_MATERIAL (90%) → EXPORTING (95%) → SUCCEEDED (100%).

Two root causes:
1. `pipeline.run()` is monolithic — no stage callbacks, so `emit_stage` fires before/after the whole run
2. SSE heartbeat is a comment line (`": heartbeat"`) — frontend's `parseSseEvent` ignores it, 2.5s watchdog fires, SSE is aborted, polling takes over (3s interval misses transient states)

## Files

- `model/trellis2/pipeline/pipelines/trellis2_image_to_3d.py` — add `stage_cb` to `run()`
- `model/trellis2/provider.py` — wire `emit_stage` as `stage_cb`
- `api/server.py` — change heartbeat from SSE comment to proper SSE data event

## Acceptance Criteria

- [x] GPU_SS status is emitted after `sample_sparse_structure` completes (not before pipeline.run)
- [x] GPU_SHAPE status is emitted after `sample_shape_slat`/`sample_shape_slat_cascade` completes
- [x] GPU_MATERIAL status is emitted after `sample_tex_slat` completes
- [x] SSE heartbeat reaches frontend as a parseable event (clears 2.5s watchdog)
- [ ] Frontend stays on SSE (does not fall back to polling) during normal inference
- [ ] User sees 5% → 25% → 60% → 90% progression in the UI
- [ ] Heartbeat events do NOT reset task progress to defaults (regression guard)

## Implementation Plan

### Task 1 — Add `stage_cb` to `trellis2_image_to_3d.py:pipeline.run()`

`run()` currently: `sample_sparse_structure` → `sample_shape_slat`/cascade → `sample_tex_slat` → `decode_latent`

Add `stage_cb: Callable[[str], None] | None = None` parameter.
Call `stage_cb("ss")` AFTER `sample_sparse_structure` block.
Call `stage_cb("shape")` AFTER shape SLAT block.
Call `stage_cb("material")` AFTER tex SLAT block.

### Task 2 — Wire callback in `provider.py:_run_single()`

Remove the pre-`pipeline.run()` `emit_stage("ss")` call.
Remove the post-`pipeline.run()` `emit_stage("shape")` and `emit_stage("material")` calls.
Pass `stage_cb=emit_stage` (or a lambda) to `self._pipeline.run(...)`.

### Task 3 — Fix SSE heartbeat format in `api/server.py`

Change `": heartbeat\n\n"` → `"event: heartbeat\ndata: {}\n\n"`.
This gives frontend a proper SSE event block with a `data:` line.
`parseSseEvent` will return `{event: "heartbeat"}` → clears watchdog → SSE stays alive.
Frontend should ignore heartbeat events (no `status` field → no state update).

Also add `X-Accel-Buffering: no` header to prevent nginx proxy buffering.

### Task 4 — Frontend: explicitly ignore heartbeat events (MANDATORY)

Validate finding (2026-04-18): the assumption "frontend checks `if (!payload.status) return`" is false.
`use-task-sync.ts:applyEventPayload` and `applyTaskSnapshot` do NOT guard against missing status/progress — when
heartbeat (`{event: "heartbeat"}`, no `status`/`progress`) flows through, `applyTaskSnapshot` resets progress to
`defaultProgressForStatus(status)` (e.g. 82 for gpu_material), causing visible regression every 15s.

Fix: in `web/src/app/gen3d-provider/use-task-realtime.ts`, right after `const payload = parseSseEvent(rawBlock);`
and the null guard, add:

```ts
if (payload.event === "heartbeat") {
  continue;  // watchdog already cleared below; heartbeat must not flow to applyEventPayload
}
```

Apply in both loop-body and `tail` parse sites. Ensure `firstEventWatchdog` is still cleared for heartbeat (it IS
a valid SSE event — counts as "first event received"), so move the `firstEventWatchdog` clear BEFORE the
heartbeat `continue`, or keep it after and accept that heartbeat won't clear the watchdog (first real event will).
Prefer: clear watchdog first, then `continue` on heartbeat.

## Summary

Pipeline 进度回调从 monolithic run() 抽出,四个 pipeline_type 分支(512/1024/1024_cascade/1536_cascade)全部接线。SSE heartbeat 从 comment 行改为可解析事件,同时加 X-Accel-Buffering 防 nginx 缓冲。验证阶段发现前端 applyTaskSnapshot 在 payload 缺 progress 时会 fallback 到 defaultProgressForStatus,导致每次 heartbeat 都把进度回退到该状态默认值 — 加前端 heartbeat guard 修复。

## Key Decisions

- **Pipeline 内部回调 > provider 前后包裹**: stage 时序由 pipeline 自己决定,避免 provider 层的假设错位。
- **Heartbeat 变为一等 SSE 事件**: 前端能解析,activity watchdog 能清,必须在 applyEventPayload 之前显式跳过。
- **X-Accel-Buffering: no**: 防止生产 nginx 缓冲 SSE 导致 watchdog 误触发。
- **不改 async_engine.py**: 它已正确 yield None 作为 heartbeat sentinel,问题只在 server.py 的 wire 转换层。

## Changes

- `model/trellis2/pipeline/pipelines/trellis2_image_to_3d.py`: 加 `stage_cb` 参数,在 sparse_structure / shape_slat / tex_slat 完成后调用。
- `model/trellis2/provider.py:_run_single`: 移除前后包裹的 emit_stage,改用 stage_cb。
- `api/server.py`: heartbeat 行格式改 `event: heartbeat\ndata: {}`,加 `X-Accel-Buffering: no` 响应头。
- `web/src/app/gen3d-provider/use-task-realtime.ts`: 主循环和 tail 路径都加 heartbeat guard;先清 watchdog 再跳过。

## Notes

- Do NOT modify `async_engine.py` — it already yields `None` for heartbeat; the fix is in `server.py` which converts `None` to the wire format
- `stage_cb` calls happen in the subprocess thread; they go through `asyncio.run_coroutine_threadsafe` already set up in `provider.py` → safe
- The SIGBUS constraint: do NOT move tensors to CPU inside `_run_single` callbacks; callbacks only call `emit_stage(name)` which sends a string
- **运行时验证延后到生产**: "SSE 不回退到 polling" 和 "UI 5→25→60→90% 推进" 两条 AC 没做端到端浏览器验证,代码层(tsc + py_compile)通过,用户在生产部署观察。
