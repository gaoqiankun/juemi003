# gen3d Phase A：架构规划

Date: 2026-03-10
Status: planning（代码未实现）
Full spec: `docs/PLAN.md`
Build guide: `AGENTS.md`

## Goal

设计并实现 gen3d 3D 生成推理服务的 Phase A 骨架：整个请求链路端到端跑通，GPU 推理用 Mock 模拟，不依赖真实模型权重。

## Architecture Decisions

- **异步引擎**：单进程 asyncio + multiprocessing GPU Worker，不用 Celery/Redis，降低依赖复杂度
- **GPU Worker 隔离**：每张 GPU 一个独立子进程，通过 `multiprocessing.Queue` 通信，避免 GIL 和 CUDA context 冲突
- **批次调度**：FlowMatchingScheduler，Request-level batching（非 iteration-level），`max_batch_size` 满了或超过 `max_queue_delay_ms` 触发
- **Provider Protocol**：`GPUWorker` 只依赖 `BaseModelProvider` 接口，Phase A 用 MockProvider，Phase B 替换为真实 Trellis2，不改 Worker 代码
- **存储**：任务状态用 SQLite（轻量，MVP 规模足够）；产物用 MinIO（S3 兼容，支持 presigned URL）
- **鉴权**：内部 Bearer Token（`INTERNAL_API_KEY`），iOS 经由 server 中转，不直连 gen3d

## Phase A Deliverables

- Mock 推理链路：submitted → preprocessing → gpu_queued → gpu_ss → gpu_shape → gpu_material → exporting → succeeded
- SSE 进度推送（`/v1/tasks/{id}/events`）
- 取消任务（gpu_queued 阶段可取消）
- pytest 全绿（无需 GPU）

## Phase Roadmap

| 阶段 | 关键内容 |
|------|---------|
| A | Mock 链路跑通（当前） |
| B | 接入真实 TRELLIS2 权重 + 真实 GLB 导出 |
| C | Prometheus 指标 |
| D | 多机 Worker（zmq/gRPC）、阶段解耦 |

## Notes

- Phase A 不实现 Redis、Grafana、多机、Hunyuan3D
- TRELLIS2 官方：`microsoft/TRELLIS.2-4B`（HuggingFace）
