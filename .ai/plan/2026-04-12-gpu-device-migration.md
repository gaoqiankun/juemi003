# GPU 显存分配器 Phase 5：跨卡迁移
Date: 2026-04-12
Status: done

## Goal

当模型所在 GPU 因外部进程占用显存持续超时（Phase 4c 的 `external_vram_wait_timeout_seconds`）时，自动把该模型迁移到其他有空间的 GPU 继续服务；任务不报错。迁移失败（没有候选卡或新卡加载出错）时模型进入 `error` 状态，由 Admin 手动重新加载。

## Acceptance Criteria

- **AC1 — 外部占用超时触发迁移**：mock 双卡环境下 stub probe 让 device 0 的 effective_free 低于 booked，超时后模型自动迁移到 device 1，任务正常完成并返回结果；allocator 的账本正确反映新卡占用、旧卡释放
- **AC2 — 迁移串行化**：同一模型 10 个并发请求同时撞上超时，只触发 **1 次** `ModelRegistry.reload`；其余请求等待同一次迁移结果（`wait_ready` 机制复用），不会出现多个请求竞相 unload/load 的乱象
- **AC3 — 迁移失败进入 error 状态**：所有候选卡都装不下时（或新卡加载抛错），reload 经由 `_load_runtime` 的失败路径把模型设为 `error`，触发 `model_unloaded_listener` → `vram_allocator.release`，后续请求从 `get_runtime` 直接抛 `RuntimeError`；Admin 可通过现有 `/api/admin/models/*/load` 路径手动重试
- **AC4 — 非外部占用错误不触发迁移**：`VRAMAllocatorError` 不是 `ExternalVRAMOccupationTimeoutError` 子类时（例如 reserve 失败、未知 device 等），`GPUStage.run` 直接向上抛错，不走 reload 路径
- **AC5 — 迁移不影响不相关模型**：双模型场景下，模型 A 在 device 0 上迁移时，device 1 上的模型 B runtime 不变、请求正常服务，B 的 scheduler/workers 不受影响
- **AC6 — 只迁移 1 次**：迁移后在新卡 retry `scheduler.acquire()` 若再次撞上 `ExternalVRAMOccupationTimeoutError`，**不再递归迁移**，直接抛错（避免全集群不够用时死循环）
- **AC7 — 质量基线**：`uv run python -m pytest tests -q` → `≥186 passed / 1 failed`（既有 baseline 不劣化）；`uv run ruff check` 不引入新问题

## Trigger 语义

```
GPUStage.run
  └─ runtime.scheduler.acquire(...)        ← 可能抛
       └─ acquire_inference(...)
            └─ _track_external_occupation_wait()
                 └─ raise ExternalVRAMOccupationTimeoutError   ← Phase 5 新子类

GPUStage 捕获 → model_registry.reload(model, exclude=(old_device,))
  ├─ 成功 → 刷新 runtime → retry acquire 1 次
  └─ 失败 → 模型 error 状态 → 任务失败
```

**重试边界**：每个任务最多触发 1 次迁移，迁移后的重试失败不再触发第二次迁移。

**触发范围**：仅 `ExternalVRAMOccupationTimeoutError`。其他 `VRAMAllocatorError` 子类型（reserve 失败、evict 失败继续走 wait 等）不触发迁移，沿用现有语义。

## Changes 范围

### 1. `engine/vram_allocator.py`
- 新增 `ExternalVRAMOccupationTimeoutError(VRAMAllocatorError)`
- `_track_external_occupation_wait` 超时路径改抛这个子类；其他 `VRAMAllocatorError` 保持原样
- 出口处 export `ExternalVRAMOccupationTimeoutError`

### 2. `engine/model_registry.py`
- `_ModelEntry` 新字段 `excluded_device_ids: tuple[str, ...] = ()`
- 新方法 `async def reload(model_name, *, exclude_device_ids) -> ModelRuntime`：
  - 用 `self._lock` 串行化同模型 reload
  - 若已有 reload 进行中（state=`loading` 且带 `excluded_device_ids` 标记）→ 直接 `wait_ready` 等它
  - 否则：调 `self.unload(normalized)` → 新建 `_ModelEntry(state="loading", excluded_device_ids=...)` → `create_task(self._load_runtime(...))`
  - 最后 `await wait_ready(normalized)` 返回新 runtime
- `_load_runtime` 从 entry 读 `excluded_device_ids`，走 `_invoke_runtime_loader`
- `_call_runtime_loader` 兼容 `exclude_device_ids` kwarg（TypeError 降级，与现有 `device_id` 兼容逻辑同构）

### 3. `api/server.py`
- `runtime_loader` 签名加 `exclude_device_ids: Iterable[str] | None = None`
- 计算 `allocatable_device_ids` 时剔除 `exclude_device_ids`
- `vram_allocator.reserve` 传 `allowed_device_ids=allocatable`，**不**再传 `preferred_device_id`（让 allocator 自行挑剩余可用）

### 4. `stages/gpu/stage.py`
- 在 `GPUStage.run` 内 `scheduler.acquire()` 处加 retry：
  ```python
  migration_attempted = False
  while True:
      try:
          slot = await runtime.scheduler.acquire(...)
          break
      except ExternalVRAMOccupationTimeoutError:
          if migration_attempted:
              raise
          migration_attempted = True
          runtime = await self._model_registry.reload(
              sequence.model,
              exclude_device_ids=(runtime.assigned_device_id,),
          )
  ```
- 日志 `gpu.model_migrated` 记录 old_device/new_device/reason

### 5. Tests
- `tests/test_vram_allocator.py`：补 `ExternalVRAMOccupationTimeoutError` 为 `VRAMAllocatorError` 子类 + 超时路径抛子类
- `tests/test_model_registry.py`（若无则新建）：`reload_migrates_to_target_device`、`reload_serialized_across_concurrent_calls`、`reload_failure_sets_error_state`
- `tests/test_gpu_stage_migration.py`（新建）：mock ModelRegistry + scheduler + stub allocator 验证 retry 语义（AC4 + AC6）

## Out of Scope

- **Phase 6**：Admin UI 显存明细展示（独立 plan 承接）
- **热交换**：不做 `GPUSlotScheduler.migrate_to()`（见上轮讨论，与"因显存不足才迁移"矛盾）
- **跨模型挤卡**：挤走其他模型的权重给自己腾空间——交给 Phase 3 的 evict 在**同卡**路径处理，不跨卡
- **迁移失败自动回退**：不尝试回旧卡重 load（旧卡也因为外部占用才触发的迁移，回退价值小）
- **i18n / Admin UI**：Phase 4c 的 `externalVramWaitTimeoutSeconds` 翻译、Phase 5 的迁移状态展示——前端单独 plan 承接

## Design Notes

- **错误子类 vs 字符串匹配**：用 `ExternalVRAMOccupationTimeoutError` 子类而非 `str(exc)` 匹配，避免字符串耦合
- **串行化借壳 `_lock`**：`ModelRegistry._lock` 当前只在 `close()` 里用，`reload()` 借用来防并发迁移，不影响 `load/unload/get_runtime` 主路径
- **迁移失败路径**：复用 `_load_runtime` 的 `except Exception` 分支，自然进入 `state="error"` 并触发 `model_unloaded_listener` → allocator.release。无需新代码
- **in-flight 请求**：`unload()` 会 stop workers（`worker.stop()`）；正在 `acquire()` 等待队列的请求会被 cancel（`asyncio.Queue` 关闭语义 + 上游 `except` 包了 allocator.release_inference 回退），cancel 后任务层自然走 task retry（由 engine 上层决定是否重跑任务，不在本 phase 范围）
- **reserve 不传 preferred**：迁移重 load 时让 allocator 从 allowed 列表自由选，避免 preferred 落在 exclude 上
- **和 Phase 4c 超时交互**：超时阈值默认 30s，迁移触发只在 30s 后发生。Admin 可通过 `externalVramWaitTimeoutSeconds` 动态调小加速验收

---

## Summary

Phase 5 在 Phase 4c 的基础上闭环了显存管理最后一块拼图：外部进程持续占用 GPU 显存导致 `acquire_inference` 超时时，任务不再直接失败，而是自动把模型迁移到其他有空间的 GPU 继续服务。迁移经由新增的 `ModelRegistry.reload()` 串行化执行，复用 load/unload 状态机和 listener；迁移失败时模型进入 error 状态，沿用既有失败路径由 Admin 手动处理。整个 Phase 1-5 的显存管理闭环由此完成。

## Key Decisions

- **新增类型化触发信号 `ExternalVRAMOccupationTimeoutError(VRAMAllocatorError)`**：避免用字符串匹配区分"外部占用超时"和"其他 VRAM 错误"，`GPUStage` 只 catch 这个窄子类，AC4/AC6 由类型系统直接保证
- **迁移路径选 Option A：ModelRegistry.reload + 任务层 retry**（对比 allocator callback / 热交换 / 任务层纯 orchestration）。理由：复用现有 load/unload/listener 机制，最少新代码；串行化由 `self._lock` + `state="loading" and excluded_device_ids` 标记天然得到
- **串行化语义借壳现有 `_lock`**：`reload()` 只在临界区持锁启动 task，`wait_ready` 在锁外轮询，避免长时间持锁阻塞其他操作
- **单次迁移上限**：每个任务最多触发 1 次迁移，第二次 `ExternalVRAMOccupationTimeoutError` 直接抛错，避免全集群显存不够时死循环
- **触发点严格限定外部占用超时**：内部争抢继续走 Phase 3 evict，reserve 失败等其他错误直接抛；迁移只在"这张卡被外部占用且持续超时"这一种情况下发生
- **迁移失败 → error 状态，不自动回退**：复用 `_load_runtime` 的 except 分支，model_unloaded_listener 自动释放 allocator 账本；Admin 通过 `/api/admin/models/*/load` 手动重试。不回退旧卡（旧卡现在仍然外部占用，回退无意义）

## Changes

### `engine/vram_allocator.py`（+6 行）
- 新增 `ExternalVRAMOccupationTimeoutError(VRAMAllocatorError)` 子类
- `_track_external_occupation_wait` 超时路径改抛该子类；其他 `VRAMAllocatorError` 抛点不变

### `engine/model_registry.py`（+73 行）
- `_ModelEntry` 新字段 `excluded_device_ids: tuple[str, ...] = ()`
- 新方法 `async def reload(model_name, *, exclude_device_ids) -> ModelRuntime`，`_lock` 串行化 + `wait_ready` 等结果
- `_invoke_runtime_loader` / `_call_runtime_loader` 传递并兼容降级新 kwarg `exclude_device_ids`（与现有 `device_id` 兼容 pattern 同构，用 `while True` 逐个 pop 不支持的 kwarg）
- `load()` 和 `unload()` 路径补 `excluded_device_ids = ()` 重置

### `api/server.py`（+19 行）
- `runtime_loader` 签名加 `exclude_device_ids: Iterable[str] | None = None`
- 计算 `allocatable_device_ids` 时剔除 exclude 集合
- `vram_allocator.reserve` 的 `preferred_device_id` 在落入 exclude 时降级为 None

### `stages/gpu/stage.py`（+39 行）
- `GPUStage.run` 在 `scheduler.acquire()` 包 `while True` retry：捕获 `ExternalVRAMOccupationTimeoutError` → `migration_attempted` 守卫 → 调 `model_registry.reload(exclude=(old_device,))` → 刷新 runtime → 重试；再次同类超时直接抛错
- 日志：`gpu.model_migration_triggered`（old_device + reason）和 `gpu.model_migrated`（old/new device）

### Tests（+278 行）
- `tests/test_vram_allocator.py`：补 `test_external_occupation_timeout_raises_subclass`
- `tests/test_model_registry.py`：5 个 reload 用例（migrate to target、allocator 账本、串行化、不影响其他模型、失败入 error）
- `tests/test_gpu_stage_migration.py`（新建）：3 个 GPUStage 语义用例（retry once、不迁移 non-target 错误、单次迁移上限）

## Notes

- 质量基线：`196 passed / 1 failed`（新增 10 个测试，既有 baseline 不劣化）
- 真实 `GPUSlotScheduler` 下 in-flight 请求在 unload 时的取消语义依赖 `worker.stop()` + `try/finally release_inference`，没有 e2e 测试覆盖，属已知残余风险
- ruff 全仓 215 历史错误未清，非本 phase scope
- Phase 1-5 整条 GPU 显存管理链路至此完成，Phase 6（Admin UI 显存明细展示）作为纯前端工作留给独立 plan 承接
- **跨模块影响 surface**：
  1. 新异常类型 `ExternalVRAMOccupationTimeoutError`（`VRAMAllocatorError` 子类）
  2. 新 `ModelRegistry.reload(model_name, *, exclude_device_ids)` API
  3. `runtime_loader` 签名变化（加 `exclude_device_ids` kwarg，有 TypeError 兼容降级）
  4. `GPUStage.run` 新增隐式行为：外部占用超时时会触发一次模型 reload
