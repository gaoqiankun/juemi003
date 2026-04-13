# VRAM 调度 in-flight 请求挂死修复（X1）
Date: 2026-04-12
Status: done

## Goal

修复 Phase 1-5 系统 review 发现的 4 个 in-flight 请求挂死风险点（H1、H2、M1、M3）。这些问题在并发场景下会导致任务永久挂起（没有超时、没有异常），必须一起修。

## 问题清单

**H1** — Phase 5 `reload()` 替换 runtime 后，旧 `GPUSlotScheduler` 上正在 `await self._available.get()` 的请求没有任何机制被唤醒或 cancel。旧 queue 永远不会再 `put`，这些 task 挂死。

**H2** — `ProcessGPUWorker.stop()` 收到 worker 回的 `"stopped"` 后直接 return，`self._pending.clear()` 只清字典但不设置 future 异常。任何正在 `await future` 的 `run_batch` caller 永久阻塞。

**M1** — Phase 3 `_evict_idle_on_device` 选出 victim 后 `await unload(victim)`。`unload` 内部 `await worker.stop()`（~5s）期间 `entry.state` 仍是 `"ready"`，其他 task 此时 `get_runtime(victim)` 能拿到即将被卸载的 runtime，产生 TOCTOU，最终撞进 H2。

**M3** — Phase 5 的 `test_gpu_stage_migration.py` 用 `FakeScheduler`，不覆盖真实 `GPUSlotScheduler` 在 reload 期间的并发行为，这些 bug 没被测出来。

## Acceptance Criteria

- **AC1 — Scheduler shutdown 唤醒所有等待者**：`GPUSlotScheduler` 新增 `shutdown()` 方法调用后，所有正在 `await acquire()` 的 task 立即抛出一个新的异常（例如 `SchedulerShutdownError`），不再挂起；已经拿到 slot 的 task 不受影响（可正常 `release()`）
- **AC2 — `reload()` 关闭旧 scheduler 后启动新 load**：`ModelRegistry.reload()` 在 `unload` 之前先调 `old_runtime.scheduler.shutdown()`，确保旧 scheduler 上所有 waiters 退出，再走 unload+新 load
- **AC3 — `GPUStage` 处理 scheduler 关闭**：`GPUStage.run` retry 循环捕获 `SchedulerShutdownError` → 从 registry 重新 `wait_ready` 拿新 runtime → 重试一次 `acquire`。和 Phase 5 的外部占用超时 retry 合并成统一的 single-shot 重试（最多一次重试，再失败直接抛）
- **AC4 — `ProcessGPUWorker.stop()` 失败 pending futures**：`stop()` 在清 `_pending` 前遍历所有未完成的 future，`set_exception(ModelProviderExecutionError("gpu_run", "worker stopped"))`，确保没有 orphan 的 `await future`
- **AC5 — `unload()` 原子化 state 转换**：引入中间 state `"unloading"`（或同效机制）。`unload()` 开头立即把 entry 标记为 `"unloading"`，`get_runtime()` 对非 `"ready"` 状态抛 `RuntimeError` 而不返回即将死亡的 runtime；Phase 3 evict 的 TOCTOU 窗口消除
- **AC6 — e2e 测试用真实 scheduler**：新增 `tests/test_gpu_scheduler_shutdown.py`（或 append 到既有文件），覆盖：
  1. 真实 `GPUSlotScheduler` 下 10 个并发 task 在 `acquire()` 等待，`shutdown()` 调用后 10 个 task 全部抛 `SchedulerShutdownError`，无挂死
  2. `reload()` 期间旧 scheduler 上的 waiter 自动被唤醒并 propagate 到 `GPUStage` retry 路径
- **AC7 — 测试 worker.stop() 取消 pending futures**：新增 `tests/test_process_gpu_worker_stop.py`（或 append），mock 出一个"已启动、有 pending future"的 `ProcessGPUWorker`，调 `stop()` 后断言 pending future 抛 `ModelProviderExecutionError`，不挂
- **AC8 — Phase 3/5 现有测试全部通过**：不 regress `test_model_registry.py`、`test_gpu_stage_migration.py` 的既有用例
- **AC9 — 质量基线**：`uv run python -m pytest tests -q` → `≥196 passed / 1 failed`；`uv run ruff check` 不引入新问题

## Changes 范围

### `stages/gpu/scheduler.py`
- 新增异常 `class SchedulerShutdownError(RuntimeError)`
- `GPUSlotScheduler.__init__` 加 `self._shutdown_event = asyncio.Event()`
- `acquire()` 改造：用 `asyncio.wait({get_task, shutdown_task}, FIRST_COMPLETED)` 或等价模式，shutdown 触发时抛 `SchedulerShutdownError`；注意已拿到 inference_allocation_id 的路径要 release 回去，避免泄漏
- 新增 `shutdown()` 方法：`self._shutdown_event.set()`
- `release()` 在 shutdown 后应为 no-op 或仅做日志（避免 put 回不再被消费的 queue）

### `engine/model_registry.py`
- `_ModelEntry.state` 扩展一个新值 `"unloading"`（和 `"loading" / "ready" / "error" / "not_loaded"` 并列）
- `get_runtime()`：state 不为 `"ready"` 时抛 `RuntimeError`（已经是这个行为的扩展，明确处理 `"unloading"`）
- `unload()` 开头立即 `entry.state = "unloading"`，然后再 cancel load_task / stop workers / 最终转 `"not_loaded"`
- `reload()` 在 `async with self._lock` 里，`unload` 前先 `old_runtime.scheduler.shutdown()`（通过 entry.runtime 取到旧 runtime），然后再 `await self.unload(normalized)`

### `stages/gpu/stage.py`
- retry 循环新增 catch `SchedulerShutdownError`：调 `self._model_registry.wait_ready(sequence.model)` 拿最新 runtime（不再调 reload，因为 reload 已经由触发方完成），重试一次 `acquire`
- 和既有的 `ExternalVRAMOccupationTimeoutError` 合并成统一 `migration_attempted` single-shot 守卫（两类异常都只允许总计一次重试）

### `stages/gpu/worker.py`
- `ProcessGPUWorker.stop()`：在 `self._pending.clear()` 之前，遍历 `self._pending.values()`，对每个未完成的 `pending.future` 调 `set_exception(ModelProviderExecutionError("gpu_run", "worker stopped"))`
- 可复用 `_fail_startup_and_pending` 的部分逻辑，或单独写一个 `_fail_pending(reason)` helper

### `tests/`
- `tests/test_gpu_scheduler_shutdown.py`（新建）：真实 `GPUSlotScheduler` 下的 shutdown / reload-while-waiting 行为（AC1、AC6）
- `tests/test_process_gpu_worker_stop.py`（新建）或 `tests/test_gpu_worker.py` append：stop() 取消 pending 行为（AC4、AC7）
- `tests/test_model_registry.py` append：`test_unload_sets_intermediate_state`、`test_get_runtime_rejects_unloading`（AC5）
- `tests/test_gpu_stage_migration.py` append：`test_retry_on_scheduler_shutdown`（AC3）

## Out of Scope

- M4（内部争抢超时）、L1/L2/L3（estimate 下限、metric、baseline 失败项）→ 留给后续 X2、X3 plan
- 不改 Phase 4 NVML probe、Phase 4c 动态配置、Phase 5 reload 串行化语义（这些 review 已经确认 OK）
- 不改 async_engine 主流程、不重构 ModelRegistry 架构
- 不碰 web/ 前端
- 不加新依赖

## Design Notes

- **`SchedulerShutdownError` vs `ExternalVRAMOccupationTimeoutError` 的差异**：前者是"scheduler 被外部 shutdown"的信号，调用方不应再尝试原 scheduler；后者是"外部占用超时"的触发信号，引发迁移。两者最终在 `GPUStage` 里都走"重新拿 runtime + 重试一次"的统一路径，但触发语义不同
- **retry 限制**：统一用 `migration_attempted: bool` single-shot 守卫，两类异常加起来最多只重试 1 次。避免新 runtime 又 shutdown 产生无限循环
- **`unloading` state 的可见范围**：仅影响 `get_runtime()` 和 `runtime_states()`；`has_ready_model()`、`ready_models()` 不把 unloading 算作 ready（当前已经是，因为只判 "ready"）
- **`reload` 里的 shutdown 顺序**：一定要先 `shutdown()` 再 `unload()`，顺序反了就会让旧 scheduler 的 waiters 先等 unload 慢路径再被唤醒，白白拉长挂起时间
- **`acquire()` 里的 inference_allocation_id 泄漏**：shutdown 抛错前要先把已经拿到的 allocation release 回去，不然 allocator 账本会漏账
- **向后兼容**：`SchedulerShutdownError` 是新异常，没有旧调用方会依赖；`unloading` state 新增，现有只比较 `"ready"` 的代码不受影响

---

## Summary

修复 Phase 1-5 系统 review 发现的 4 个 in-flight 请求挂死风险点（H1/H2/M1/M3）。修复前：(a) Phase 5 `reload()` 后，旧 `GPUSlotScheduler` 上 `await queue.get()` 的 task 永久挂起；(b) `ProcessGPUWorker.stop()` 不 fail pending run_batch futures，导致正在 `await future` 的任务挂起；(c) Phase 3 evict 期间的 TOCTOU 窗口让新请求进入 `entry.state == "ready"` 但 worker 正在 stop 的模型；(d) 测试覆盖没用真实 scheduler，bug 没被抓到。修复后所有并发路径都有明确的 cancel/fail 语义。

## Key Decisions

- **新增 `SchedulerShutdownError` + `GPUSlotScheduler.shutdown()`**：用 `asyncio.wait({get_task, shutdown_task}, FIRST_COMPLETED)` 模式让正在 `acquire()` 的 task 在 shutdown 时立刻抛错，不改 `_available: asyncio.Queue[str]` 类型，最小侵入
- **竞态：shutdown 和 get 同时完成时保护 slot**：`_restore_slot_from_task` 检测到 get_task 拿到 device_id 但 shutdown 赢了的情况，把 device_id `put_nowait` 回 queue，避免 slot 永久消失
- **新增 `_ModelEntry.state = "unloading"` 中间态**：`unload()` 开头立即转进，消除 worker.stop() 期间 TOCTOU。`get_runtime()` 的既有 `state != "ready"` 判定直接兼容新 state，无需额外改 caller
- **`reload()` 在 unload 前先 shutdown 旧 scheduler**：通过 `getattr + callable` 兜底调用，对 mock 对象安全
- **`ProcessGPUWorker._fail_pending(reason)` 抽出 helper**：从 `_fail_startup_and_pending` 复用逻辑，`stop()` 和启动失败路径共用，保证任何 cleanup 路径都会 set_exception pending futures
- **`GPUStage` retry 合并**：`SchedulerShutdownError` 走 `wait_ready`（不触发 reload，别人已经触发），`ExternalVRAMOccupationTimeoutError` 走 `reload`（主动触发迁移），共享 `migration_attempted` single-shot 守卫，两类异常加起来最多重试 1 次
- **测试层：真实 `GPUSlotScheduler` + 真实 `ModelRegistry`**：`test_gpu_scheduler_shutdown.py` 两个用例用真组件 e2e，不再用 FakeScheduler，覆盖之前 Phase 5 测试的盲区

## Changes

### `stages/gpu/scheduler.py`（+53/-5）
- 新增 `class SchedulerShutdownError(RuntimeError)`
- `__init__` 加 `self._shutdown_event = asyncio.Event()`
- `acquire()`：`asyncio.wait` 同时等 `_available.get()` 和 `_shutdown_event.wait()`，shutdown 赢则抛 `SchedulerShutdownError`；异常路径 release 已获得的 `inference_allocation_id`，避免 allocator 账本漏账；catch 从 `Exception` 扩到 `BaseException`
- 新增 `shutdown()` 方法
- `release()` 在 shutdown 后 early return 不回填 queue
- 新增 helper `_cancel_task`、`_restore_slot_from_task`（处理竞态 slot 归还）

### `engine/model_registry.py`（+9/-1）
- `reload()` 在 unload 前先用 `getattr + callable` 兜底调用 `old_runtime.scheduler.shutdown()`
- `unload()` 开头立即 `entry.state = "unloading"`，并用 `if entry.state == "unloading": return` 防重入
- `get_runtime()` 错误信息带当前 state

### `stages/gpu/stage.py`（+11/-0）
- `GPUStage.run` retry 循环新增 `except SchedulerShutdownError` 分支：调 `wait_ready` 拿最新 runtime，不调 reload；与 `ExternalVRAMOccupationTimeoutError` 共享 `migration_attempted` 守卫
- 日志 `gpu.acquire_retry_after_scheduler_shutdown`

### `stages/gpu/worker.py`（+4/-1）
- 抽出 `_fail_pending(error_message)` helper
- `stop()` 把 `self._pending.clear()` 换成 `self._fail_pending("worker stopped")`
- `_fail_startup_and_pending` 复用 `_fail_pending`

### Tests（+385 行）
- `tests/test_gpu_scheduler_shutdown.py`（新建，120 行）：2 个真实 scheduler 用例（shutdown 唤醒所有 waiters、reload 路径 e2e）
- `tests/test_process_gpu_worker_stop.py`（新建，89 行）：mock process + 注入 pending future，验证 stop 后 future set_exception
- `tests/test_model_registry.py`（+66 行）：`test_unload_sets_intermediate_state`、`test_get_runtime_rejects_unloading`
- `tests/test_gpu_stage_migration.py`（+114 行）：`test_retry_on_scheduler_shutdown`、`test_scheduler_shutdown_and_external_timeout_share_single_retry_guard`

## Notes

- 质量基线：`203 passed / 1 failed`（Phase 5 的 196 + 本 phase 新增 7 个测试），pre-existing 失败项不变
- `ruff check engine/ stages/gpu/` 仅剩 2 条 pre-existing C901（`weight_manager.get_storage_breakdown`、`worker._pump_responses`），未引入新问题
- 跨模块影响 surface：
  1. 新异常 `SchedulerShutdownError`（`stages/gpu/scheduler.py`）
  2. 新 state `"unloading"`（`_ModelEntry.state`）
  3. 新 API `GPUSlotScheduler.shutdown()`
  4. `ProcessGPUWorker.stop()` 语义变化：现在会 set_exception 所有 pending run_batch futures
  5. `GPUStage.run` 现在在两类异常（scheduler shutdown、external occupation timeout）上都会尝试重试一次
- 后续剩余 X2（内部争抢超时 + metric）、X3（estimate 下限 + baseline 失败项）未开始
