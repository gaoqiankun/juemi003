# ModelRegistry wait_ready 轮询等待语义调整
Date: 2026-03-24
Status: done

Date / Status: 2026-03-24 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
调整 `ModelRegistry.wait_ready()`：不再对 `not_loaded` 立即报错，改为轮询等待调度器触发加载，并在超时时给出明确错误信息。

## Key Decisions
- `wait_ready()` 增加 `timeout_seconds` 参数，默认 `1800s`（30 分钟）。
- 状态机行为：
  - `ready`：立即返回 runtime。
  - `error`：立即抛出 `failed to load`（附带底层错误）。
  - `loading`：轮询等待直到 `ready` / `error` / 超时。
  - `not_loaded`：轮询等待调度器触发加载，超时仍为 `not_loaded` 时抛出 `model X still not loaded after timeout`。
- 轮询 sleep 使用模块加载时缓存的原始 `asyncio.sleep`，避免测试中 monkeypatch `asyncio.sleep` 导致无让出的忙等。

## Changes
- `engine/model_registry.py`
  - `ModelRegistry` 新增 `_WAIT_READY_POLL_SECONDS` 和 `_WAIT_READY_TIMEOUT_SECONDS` 常量。
  - `wait_ready()` 改为按状态循环轮询，并支持超时分支错误信息。
  - 增加 `_ORIGINAL_ASYNCIO_SLEEP`，轮询时使用原始 sleep。
- `tests/test_model_registry.py`
  - 删除 `test_wait_ready_raises_if_not_loading`。
  - 新增 `test_wait_ready_waits_for_scheduler_to_load`，覆盖 `not_loaded -> loading -> ready` 路径。
  - 清理无用 import：移除 `ModelRegistryLoadError`。

## Notes
- 验证：
  - `.venv/bin/python -m pytest tests/test_model_registry.py -q` → 4 passed
  - `.venv/bin/python -m pytest tests -q` → 159 passed
