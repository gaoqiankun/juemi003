# async_engine 模块拆分（ETA / SSE / Webhook）
Date: 2026-03-25
Status: done

Date / Status: 2026-03-25 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
- 在不改变 worker 主循环与 cleanup 语义的前提下，把 `engine/async_engine.py` 中 ETA 估算、SSE 事件发布/回放、webhook payload 与重试逻辑提取为无状态模块，降低主文件复杂度。

## Key Decisions
- 保持 `AsyncGen3DEngine` 对外 API 与 import 路径不变（`gen3d.engine.async_engine` 仍为入口）。
- `engine/async_engine_eta.py` 只做 ETA 纯计算，不直接触发任何 IO。
- `engine/async_engine_events.py` 负责 SSE 队列管理、payload 构建、历史回放与 publish。
- `engine/async_engine_webhook.py` 负责 webhook payload、重试与默认 sender；`async_engine.py` 仅注入依赖并触发调用。
- worker 循环与 cleanup 处理逻辑保持原有行为。

## Changes
- 新增 `engine/async_engine_eta.py`
  - `decorate_sequence_eta`、`estimate_queued_wait`、`estimate_processing_wait`、stage mean 汇总 helper。
- 新增 `engine/async_engine_events.py`
  - SSE subscriber 队列注册/注销、事件 payload 构建、历史 replay、事件 publish、终态判断 helper。
- 新增 `engine/async_engine_webhook.py`
  - `build_webhook_payload`、指数退避、`send_webhook_with_retries`、`build_default_webhook_sender`。
- 修改 `engine/async_engine.py`
  - 接入上述 3 个模块；保留主类、worker loop、cleanup。
  - `submit_task` 与 `_decorate_sequence` 改为通过 ETA 模块计算等待时间。
  - `stream_events` / `_publish_update` 改为通过 events + webhook 模块完成回放、分发与回调。
  - 删除未使用的 startup prewarm dispatch 辅助方法，最终行数降至 400。

## Notes
- 基线：`.venv/bin/python -m pytest tests -q` = `163 passed`。
- 验收：
  - `.venv/bin/python -m pytest tests -q` = `163 passed`
  - `.venv/bin/ruff check engine/async_engine.py engine/async_engine_eta.py engine/async_engine_events.py engine/async_engine_webhook.py` = `All checks passed!`
  - `.venv/bin/ruff check .` 在仓库中存在历史存量问题（与本次改动无关），本次改动文件未引入新增 ruff 错误。
