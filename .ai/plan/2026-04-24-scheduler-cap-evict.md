# Scheduler 超 cap 自动 LRU evict
Date: 2026-04-24
Status: done

## Summary

修复 `ModelScheduler._load_or_queue` 在超 `max_loaded_models` cap 时静默丢弃加载请求的 bug。原实现直接 `return` 导致任何入口（admin 手动加载、新任务入队、startup scan、on_model_loaded 重扫）在达 cap 时无反应。改为：候选集筛选 ready 且非 busy 且非目标 → 按 `_last_used` tick 升序 LRU evict 一个 → 继续加载目标。无候选时 raise `SchedulerCapReachedError`，`request_load` 路径透传到 API 层返回 HTTP 409；其他路径 swallow + warning 日志。新增/更新 6 条测试（220 passed），ruff 无新增。

## Goal

补齐 `ModelScheduler._load_or_queue` 在超 `max_loaded_models` cap 时的驱逐逻辑。当前该分支直接 `return`，导致任何入口（admin 面板手动加载、新 gen3d 任务触发、startup scan、`on_model_loaded` 重扫）在达到 cap 时都会静默丢弃加载请求，新模型永远无法进入。

原设计（`2026-03-23-scheduler-startup-scan.md`、`2026-03-24-model-scheduler-on-model-loaded-rescan.md`）的语义是"超 cap 走驱逐链"，但驱逐这一步的代码从未实现。本 plan 补齐，语义统一。

## Scope

**In scope**：
- `engine/model_scheduler.py::_load_or_queue` 超 cap 分支改为 LRU evict
- `engine/model_scheduler.py` 新增错误类型 `SchedulerCapReachedError`（供 API 捕获）
- `api/server.py::load_model` 端点捕获新异常 → 返回 409 + 明确原因
- 新增对应单测

**Out of scope**（不在本期）：
- pending-load 队列（若无候选不排队，直接告错，由用户决策后再触发）
- 前端 toast / UI 适配（用户可观察 API 响应，后续 plan 承接）
- VRAM allocator 的 evict 路径改动（独立、已在工作）
- `on_task_completed` 里 `_quota_exceeded` 计数后的驱逐（本 plan 只解决 cap 超限那条路，配额轮转另论）

## Key Decisions

1. **Busy 检查方式**：通过 `ModelRegistry.get_worker(model_name)` 拿 ready 模型的 worker，读 `worker.inference_busy` 判断。理由：registry 是 scheduler 已有依赖，无需引入 allocator 反向引用。

2. **LRU 来源**：复用 `ModelScheduler._last_used` tick（已有，`get_last_used_tick()` 也在 VRAM evict 路径使用）。统一 LRU 语义，避免双源定义。

3. **候选集合过滤条件**（必须同时满足）：
   - `state == "ready"`（loading 中的模型不能打断）
   - `worker is not None` 且 `not worker.inference_busy`
   - 不是本次要加载的目标模型

4. **挑选算法**：按 `_last_used` tick 升序取最旧一个。若多个 tick 相同（冷启后未使用），按 model_name 字典序稳定。

5. **Unload 调用**：`await self._model_registry.unload(candidate)`。该调用会等 inference_busy 清零，但我们已经过滤掉 busy 的候选，所以正常情况下应立即进入实际 unload（`worker.evict()` → 释放权重 + unregister）。

6. **锁策略**：evict 路径不持 `self._lock`。`_load_or_queue` 当前就不在 `self._lock` 内（只有 `_touch_locked` 进锁），保持一致。scheduler 现有的并发保证由 registry 的 entry state + 各 hook 幂等性承担，不变。

7. **无候选时行为**：记 `scheduler.cap_reached_no_evict_candidate` warning 日志，raise `SchedulerCapReachedError(reason="all ready models busy")`。`request_load` 的 try/except 改为只吞 "其他 Exception"，让 `SchedulerCapReachedError` 传到 API 层。

8. **API 响应码**：选 409 Conflict（"状态冲突：全部 ready 模型都在忙"），不用 503（503 语义偏"服务不可用/过载"，这里是业务状态约束）。响应体：
   ```json
   {"detail": "cannot evict: all ready models are currently in inference"}
   ```

9. **`on_task_queued` / startup scan / `on_model_loaded` 重扫路径**：这些入口也调 `_load_or_queue`，异常由其外层现有 try/except 捕获并 warning 日志（现状保持）。新异常不会传到 gen3d 任务层 — 任务仍留在 DB queued，下次 `on_model_loaded` 或 `on_task_completed`（未来若接入）会重试。

10. **Mock 模式 / scheduler disabled**：`request_load` 首行 `if not self._enabled: return` 保持，mock 不受影响。

## Changes

### `engine/model_scheduler.py`

**新增异常类**：
```python
class SchedulerCapReachedError(Exception):
    """Raised by _load_or_queue when at cap and no evictable candidate."""
```

**`_load_or_queue` 改写**：
- 保留前置 state 检查（ready / loading 短路）
- 超 cap 分支改为：
  1. 收集所有 ready 且非 busy 且非目标的模型
  2. 无候选 → warning 日志 + `raise SchedulerCapReachedError(...)`
  3. 有候选 → 按 `_last_used` tick 升序取首个
  4. `await self._model_registry.unload(candidate)`
  5. 日志 `scheduler.evicted_lru` 记 `requester` / `evicted` / `tick`
  6. 继续原 `self._model_registry.load(target_model)`

**`request_load` 的 try/except**：
- 当前 `except Exception` 全吞。改为：让 `SchedulerCapReachedError` 透传，其他异常保持现有 warning 吞掉行为。

### `api/server.py::load_model`

`await app_container.model_scheduler.request_load(model_id)` 外包 try/except：
```python
try:
    await app_container.model_scheduler.request_load(model_id)
except SchedulerCapReachedError as exc:
    raise HTTPException(status_code=409, detail=str(exc)) from exc
```

### `tests/test_model_scheduler.py`

新增：
- `test_load_or_queue_evicts_lru_when_at_cap`：max=2，A/B ready（A 先用过，tick 较旧），第三次 request_load C → A 被 unload，C 进入 loading
- `test_load_or_queue_evict_skips_busy_models`：max=2，A busy（inference_busy=True）、B 空闲，request C → B 被 evict 而非 A
- `test_load_or_queue_raises_when_all_ready_busy`：max=2，A/B 都 busy → request C 触发 `SchedulerCapReachedError`
- `test_load_or_queue_noop_when_disabled`：回归原有 mock 路径不变
- `test_on_model_loaded_rescan_still_works_after_evict`：A evicted, C loading，`on_model_loaded("C")` 重扫不会误 evict C

### `tests/test_api.py`

新增：
- `test_api_load_model_returns_409_when_no_evict_candidate`：mock scheduler 抛 `SchedulerCapReachedError` → 端点返回 409

## Acceptance Criteria

- `uv run python -m pytest tests -q` 全量通过（≥ 163 passed baseline + 新增 5-6 条）
- `uv run ruff check .` 无新增 issue
- 单测覆盖：evict 正向、busy 跳过、无候选报错、disabled 路径、重扫兼容、API 409 传播 六项
- 手动验证（deploy 机，max_loaded_models=2）：
  - 启动 → 默认模型 ready
  - admin 面板点加载第二个 → ready（不触发 evict）
  - admin 面板点加载第三个 Step1X-3D → docker 日志见 `scheduler.evicted_lru` + 第一个模型 `model.unloaded` + Step1X-3D `model.loading` → `model.ready`
  - Step1X-3D 加载过程中的 vae/UNet 两个警告可被观察（本期不处理致命性判断，遗留给下个调查）
- `.ai/decisions.md` 追加一条：scheduler cap 超限自动 LRU evict 决策 + 与 VRAM evict 路径的职责分工

## Notes

- 本 plan 修的是"cap 自动驱逐"这条链；`on_task_completed` 里 `_quota_exceeded` 标记后的"配额轮转"另一条链仍未驱动，是独立 bug，留给后续 plan
- VRAM allocator 的 `_evict_worker` / `_idle_candidates_on` 是另一套评估体系（推理时显存不够触发），和本 plan 的 cap 驱逐互不干扰：前者按 device 维度 + allocator 自己管 inference_busy 状态，后者按全局 cap 计数 + 过滤 busy
- 若后续需要 pending-load 队列（admin 想批量切换模型且接受等待），再开新 plan 做方案 C
- `SchedulerCapReachedError` 异常放在 `model_scheduler.py` 模块内，`api/server.py` import 时同模块导入，不新增 exceptions 公共模块
