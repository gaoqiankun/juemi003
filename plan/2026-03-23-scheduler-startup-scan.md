# Scheduler 完整修复：startup scan + wait_ready bypass 封堵
Date: 2026-03-23
Status: done
Commits: N/A（按 AGENTS.md 要求未执行 commit）

## Goal

彻底封堵两个调度漏洞：
1. 重启后 DB 已有的 queued 任务无触发入口
2. pipeline 内 `wait_ready()` 直接调 `registry.load()`，绕过 scheduler 槽位限制

## 问题分析

### 漏洞 1：重启后 queued 任务无触发
`on_task_queued` 只在新任务提交时触发。重启后 DB 里的存量 queued 任务没有任何入口通知 scheduler，
只能靠 pipeline 内部的 `wait_ready` auto-load 兜底，而这个兜底本身就是漏洞 2。

### 漏洞 2：wait_ready bypass
`ModelRegistry.wait_ready()` 内部调了 `self.load(normalized)`，任何调用方都能绕过 scheduler
直接触发模型加载。Worker 并发处理不同模型任务时，slot 上限形同虚设。

## 修复方案

### 改动 1：wait_ready 变为纯等待

`ModelRegistry.wait_ready()` 去掉 `self.load(normalized)` 这一行。
如果调用时 entry 不存在或 state 为 `not_loaded`，立即 raise `ModelRegistryLoadError`（不挂起）。
`wait_ready` 的语义变为：**等待一个已经在加载中的模型就绪**，不负责触发加载。

### 改动 2：worker 在运行前显式请求 scheduler

`async_engine.py` 的 worker 循环在调用 `pipeline.run_sequence(task)` 之前，
先调 `await self._model_scheduler.request_load(task.model)`。

这样无论任务来自何处（新提交 or 重启存量），worker 拿到任务时都会经过 scheduler 确认加载，
scheduler 成为 `registry.load()` 的唯一调用方。

流程变为：
```
worker 取到 task
  → scheduler.request_load(model)   # 确保 scheduler 知道并触发加载
  → registry.wait_ready(model)      # 纯等待，阻塞直到 ready 或 error
  → pipeline.run_sequence(task)
```

### 改动 3：scheduler startup scan

`ModelScheduler.initialize()` 末尾新增 startup scan：

1. 调 `task_store.get_oldest_queued_task_time_by_model()` 获取每个模型最早 queued 任务的创建时间
   （需在 task_store 新增此查询方法）
2. 按最早创建时间升序排列（等待最久的模型优先）
3. 依次调 `_load_or_queue(model_id)`，受 `max_loaded_models` 自然约束，多余的模型等 worker
   完成任务后通过 `on_task_completed` → 驱逐 → 加载链继续

排序依据用"最早任务时间"而非"pending 数量"，更符合公平调度语义。

### 改动 4：request_load 在 scheduler disabled 时的行为

`enabled=False`（mock 模式）时 `request_load` 直接 return，不变。
但此时 `wait_ready` 已不再 auto-load，mock 模式下模型是 eager loaded 的（startup 时就 ready），
所以 worker 调 `wait_ready` 时 entry 已经是 ready，不会 raise。需确认 mock 模式启动流程不受影响。

## Changes

**后端**
- `engine/model_registry.py`：
  - `wait_ready()` 去掉 `self.load(normalized)`
  - entry 不存在或 state 为 `not_loaded` 时直接 raise，不 await event
- `engine/async_engine.py`：
  - worker 循环在 `pipeline.run_sequence` 前加 `await self._model_scheduler.request_load(task.model)`
  - `wait_ready` 调用保持不变（现在是纯等待）
  - mock 模式下追加安全兜底：scheduler disabled 且模型仍 `not_loaded` 时允许 direct `registry.load()`，
    防止 legacy `model="trellis"` 任务在 prewarm 竞态下误失败
  - startup prewarm 改为在 `engine.start()` 内立即调度（仍异步加载，不阻塞启动），降低竞态窗口
- `engine/model_scheduler.py`：
  - `initialize()` 末尾加 startup scan 逻辑
  - `enabled=False` 时 startup scan 跳过（no-op）
  - startup scan 按 `task_store.get_oldest_queued_task_time_by_model()` 返回的最早创建时间升序调度
- `storage/task_store.py`：
  - 新增 `get_oldest_queued_task_time_by_model() -> dict[str, str]`
    返回 `{model_id: iso_timestamp}`，只包含有 queued 任务的模型

**测试**
- `test_model_registry.py`：
  - `test_wait_ready_raises_if_not_loading`：未触发 load 时 wait_ready 立即 raise
  - 修改 `test_model_registry_retry_after_error`：load() 需在 wait_ready() 前显式调用（原测试已是这样，确认无变化）
- `test_model_scheduler.py`：
  - `test_scheduler_startup_scan_loads_model_with_oldest_task`
  - `test_scheduler_startup_scan_respects_slot_limit`
  - `test_scheduler_startup_scan_skips_when_disabled`
  - `test_scheduler_normalize_model_name_keeps_empty_string`（保留已有覆盖）
- `test_task_store.py`：
  - `test_get_oldest_queued_task_time_by_model`
- `test_api.py` 或 `test_async_engine.py`：
  - `test_worker_calls_request_load_before_wait_ready`：worker 在 `wait_ready` 前调了 scheduler
  - `test_mock_mode_scheduler_disabled_with_eager_loaded_model_still_processes_tasks`

## 验收标准

- `python -m pytest tests -q` 全部通过，总数 ≥ 152
- `wait_ready("model_not_loading")` 立即 raise，不挂起
- mock 模式下 worker 正常处理任务（scheduler disabled 时 request_load no-op，模型已 eager loaded）
- startup scan 按最早任务时间排序，优先加载等待最久的模型
- worker 处理任务前必经 `scheduler.request_load`，`registry.load()` 只由 scheduler 调用

## Notes

- `wait_ready` 改为纯等待后，现有调用 `wait_ready` 而未显式 `load()` 的地方会 raise，
  需全局搜索确认只有 async_engine worker 这一处（pipeline 内部的调用路径）
- startup scan 是 initialize() 的一部分，在 scheduler 和 registry 都初始化完成后执行
- 本轮不改 `_resolve_model_runtime` 里的 `wait_ready` 调用（那是 eager load 路径，在服务启动时调用，
  此时 scheduler 还未 initialized，需单独评估或跳过）
- 全量验证：`python -m pytest tests -q` → `159 passed`
