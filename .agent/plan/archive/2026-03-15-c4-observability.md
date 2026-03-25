# C4 · 基础可观测性
Date: 2026-03-15
Status: done
Commits: none

## Goal
补齐生产环境最低限度的可观测能力：结构化日志 + task_id 全链路贯穿 + 核心 Prometheus 指标，使线上出问题时能快速定位。

## Key Decisions
- 用 structlog 做结构化日志，task_id 在整条处理链中自动绑定到上下文
- 核心指标：队列深度、任务端到端延迟（histogram）、各阶段耗时、成功/失败率、webhook 成败
- 不引入外部日志聚合服务（Grafana/Loki 等），只保证日志格式机器可读、指标 Prometheus 可抓
- C1 之后执行，可以修改 stages/preprocess/stage.py 等共享文件

## Changes
| 文件 | 变更说明 |
|------|---------|
| serve.py | 配置 structlog，json 格式输出 |
| requirements.txt | 新增 structlog、prometheus-client 依赖 |
| observability/logging.py | structlog + stdlib logging JSON 输出配置 |
| observability/metrics.py | 新增队列深度、任务/阶段耗时、终态计数、webhook 结果等 Prometheus 指标 |
| engine/pipeline.py | 队列深度 gauge、终态 task 指标、task 级结构化日志 |
| engine/async_engine.py | 任务提交 / webhook 成败日志与 webhook counter |
| stages/preprocess/stage.py | preprocess 开始/结束/失败日志与耗时 histogram |
| stages/gpu/stage.py | gpu 开始/结束/失败日志与耗时 histogram |
| stages/export/stage.py | export 开始/结束/失败日志与耗时 histogram |
| tests/test_api.py | 新增 3 条 `test_metrics_*`，补齐成功/失败任务与 webhook Prometheus 指标断言 |
| README.md / docs/PLAN.md | 同步 observability 能力、指标名和当前测试基线 |

## Notes
- C1 完成后执行，无文件交叉冲突
- C2（可靠性）在 C4 之后
- 2026-03-15 补充 metrics 覆盖后，`pytest tests -q` 结果更新为 `26 passed`
- 手工 sanity check：
  - `configure_logging()` 输出 JSON 日志，`task_id` 会出现在上下文字段里
  - 跑一次 mock 任务后，`/metrics` 中可见 `gen3d_task_total{status="succeeded"}` 与 `gen3d_task_duration_seconds_count{status="succeeded"}`
