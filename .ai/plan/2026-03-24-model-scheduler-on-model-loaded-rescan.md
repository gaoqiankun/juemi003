# ModelScheduler on_model_loaded 后补扫 pending 模型
Date: 2026-03-24
Status: done

Date / Status: 2026-03-24 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
修复模型调度中的“加载请求丢失”窗口：当 `on_task_queued()` 在槽位被 `loading` 模型占满时无法触发驱逐，等模型变 `ready` 后应自动重扫 pending 模型并继续调度。

## Key Decisions
- 在 `on_model_loaded()` 现有 quota/LRU 重置逻辑之后，追加一次 `_startup_scan_queued_models()`。
- 保持“先 touch 再扫描”的顺序，确保刚加载完成模型的 LRU tick 最新，扫描触发驱逐时不优先淘汰它。
- 新增单测覆盖两类行为：
  - `loading` 阶段被阻塞的模型在另一个模型 `ready` 后可自动触发加载；
  - `on_model_loaded()` 扫描不会立刻驱逐刚加载完成的模型（在有其他可驱逐候选时）。

## Changes
- `engine/model_scheduler.py`
  - `on_model_loaded()` 尾部新增 `await self._startup_scan_queued_models()`。
- `tests/test_model_scheduler.py`
  - 新增 `test_scheduler_on_model_loaded_rescans_and_loads_pending_model`
  - 新增 `test_scheduler_on_model_loaded_scan_does_not_evict_just_loaded_model`
- `tests/test_api.py`
  - 调整两个 HunYuan3D provider 单测的 fake shape 返回值为 list，匹配当前 provider 的 `out[0]` 取值路径，保证全量测试绿灯。

## Notes
- 验证：
  - `.venv/bin/python -m pytest tests/test_model_scheduler.py -q` → 11 passed
  - `.venv/bin/python -m pytest tests -q` → 161 passed
