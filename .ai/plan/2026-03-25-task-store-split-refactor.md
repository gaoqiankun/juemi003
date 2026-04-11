# task_store 模块化拆分重构
Date: 2026-03-25
Status: done

Date / Status: 2026-03-25 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
将 `storage/task_store.py` 从单文件拆分为 facade + 5 个子模块，保留现有对外导入路径与行为语义。

## Key Decisions
- `claim_next_queued_task` 乐观锁流程（先查可抢任务，再锁内条件更新+commit，失败重试）保持不变。
- facade 保留 `TaskStore` 与兼容导出（含 `TaskIdempotencyConflictError`、`_serialize_datetime` 等）。
- SQL 语句与字段语义尽量原样迁移，避免行为漂移。

## Changes
- 已新增：`storage/task_store_schema.py`（初始化/建表/列补齐/PRAGMA）
- 已新增：`storage/task_store_codec.py`（datetime/status 序列化 + row→sequence）
- 已新增：`storage/task_store_mutations.py`（写路径 + idempotency 冲突处理）
- 已新增：`storage/task_store_queries.py`（查询/分页/队列 claim/计数）
- 已新增：`storage/task_store_analytics.py`（stage stats/throughput/recent/active）
- 已改造：`storage/task_store.py` 为 facade（当前 85 行，≤ 160），保留兼容导出
- 关键语义：`claim_next_queued_task` 仍保留“先查候选、锁内条件更新+commit、失败重试”乐观锁流程

## Notes
- 开工前基线：`.venv/bin/python -m pytest tests -q` → `163 passed`
- 验收：
  - `.venv/bin/python -m pytest tests -q` → `163 passed`
  - `.venv/bin/ruff check . --statistics` → 51 个存量问题（E402/C901/F401/F841），无新增问题
  - `.venv/bin/ruff check storage/task_store.py storage/task_store_schema.py storage/task_store_codec.py storage/task_store_mutations.py storage/task_store_queries.py storage/task_store_analytics.py` → All checks passed
