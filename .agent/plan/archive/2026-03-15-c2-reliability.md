# C2 · 基础可靠性
Date: 2026-03-15
Status: done
Commits: none

## Goal
解决公测前必须修复的三个可靠性问题：服务重启后中间态任务恢复、webhook 失败重试、幂等 key 竞态修复。

## Key Decisions
- 启动时扫描中间态任务（非终态、非 submitted/preprocessing 可安全重排），超时或重入队列
- webhook 失败加指数退避重试（最多 N 次，可配置），失败后记录到 task_events
- idempotency_key 改为数据库唯一约束 + 捕获冲突返回已有任务，API 统一返回稳定语义
- 运行中任务取消：加超时机制，超时后强制标记 failed，不要求完美中断

## Changes
| 文件 | 变更说明 |
|------|---------|
| config.py | 新增 `WEBHOOK_MAX_RETRIES`、`TASK_TIMEOUT_SECONDS` 配置并集中注释 |
| storage/task_store.py | 增加非终态扫描、task_events 追加接口、幂等 key UNIQUE 冲突返回已有任务 |
| engine/pipeline.py | 启动恢复 submitted/preprocessing 重入队，gpu_queued+ 中断失败，超时任务失败，并输出恢复摘要日志 |
| engine/async_engine.py | webhook 指数退避重试、task_events 记录 retry/success/failure、幂等冲突返回稳定语义 |
| api/server.py | 重复 idempotency key 返回 HTTP 200 + 已有任务数据 |
| tests/test_api.py / tests/test_pipeline.py | 新增恢复、webhook 重试、idempotency conflict 覆盖，测试总数从 26 增长到 31 |
| README.md | 同步恢复策略、webhook 重试和新增配置 |

## Notes
- C4 完成后执行
- C3（多卡并发）在 C2 之后
- `pytest tests -q` 结果：`31 passed`
- 启动日志新增 `task.recovery_summary`，包含扫描数、重入队数、中断失败数和超时失败数
- webhook retry 事件写入 `task_events`：`webhook_retry` / `webhook_delivered` / `webhook_failed`
