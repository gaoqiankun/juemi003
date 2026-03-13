# gen3d Phase A：架构规划

Date: 2026-03-10
Status: done
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

## Changes

- 新建最小可运行服务骨架：`config.py`、`serve.py`、`api/server.py`、`api/schemas.py`
- 落地 `RequestSequence` 状态机，先持久化 `submitted` / `preprocessing` / `gpu_queued`，并保留后续 `gpu_ss` / `gpu_shape` / `gpu_material` / `exporting` / `uploading` / 终态枚举
- 落地 `storage/task_store.py`，用 SQLite 建 `tasks` 和 `task_events`，支持建表、创建任务、按 `task_id` / `idempotency_key` 查询、状态更新、可恢复任务扫描
- 落地 `engine/async_engine.py` + `engine/pipeline.py`，把提交任务和后台状态推进从 API 层解耦，当前先推进到 `gpu_queued`
- 建立 `stages/preprocess/stage.py`、`stages/gpu/stage.py`、`stages/export/stage.py` 占位实现，避免后续接入真实 preprocess / gpu / export 时推翻接口
- 建立 `model/base.py`、`model/trellis2/provider.py`、`model/hunyuan3d/provider.py`、`storage/artifact_store.py`、`observability/metrics.py` 作为下一轮扩展点
- 补充 `tests/test_api.py`、`tests/test_pipeline.py`、`tests/test_scheduler.py`，本地 `.venv` 下 `pytest` 结果为 `5 passed`
- 第二轮把三段链路补齐为可运行的 Mock pipeline：`preprocessing -> gpu_queued -> gpu_ss -> gpu_shape -> gpu_material -> exporting -> succeeded`
- `BaseStage` 新增中间状态上报回调，`PipelineCoordinator` 新增统一的持久化/监听分发入口，为后续 SSE / webhook 复用同一事件面
- `MockTrellis2Provider`、`GPUWorker`、`GPUStage` 已按 provider/worker/stage 分层接通，GPU 侧阶段推进和失败注入通过 provider 回调驱动
- `ExportStage` 接通 `ArtifactStore` 本地占位产物写入，成功任务会持久化 mock artifact 元数据并在 `GET /v1/tasks/{id}` 返回
- 新增失败分支：支持通过 `options.mock_failure_stage` 在 `preprocessing` / `gpu_ss` / `gpu_shape` / `gpu_material` / `exporting` 注入 mock 失败，并落库 `failed_stage` / `error_message`
- 测试扩展到 API 轮询观察中间状态、成功 artifact 返回、失败诊断返回，以及 pipeline 事件历史校验；当前 `.venv/bin/pytest tests -q` 结果为 `7 passed`
- 第三轮补齐 `GET /v1/tasks/{id}/events`、`POST /v1/tasks/{id}/cancel`、`GET /v1/tasks/{id}/artifacts`，API 仍只做协议转换，状态流继续由 Engine/Pipeline 驱动
- `PipelineCoordinator` 新增统一取消入口，`gpu_queued` 阶段可稳定转为 `cancelled` 并沿用同一条 task update / listener / task_events 落库链路
- `AsyncGen3DEngine` 新增历史回放 + 实时订阅式事件流、终态 webhook 分发、artifact 查询封装，避免在 API 层再维护一份状态同步逻辑
- task_events 元数据已统一补齐 `status` / `current_stage` / `progress`，SSE 和 webhook payload 都复用同一份终态/事件语义
- webhook 当前在 `succeeded` / `failed` 终态触发，采用基础容错；本轮不引入复杂重试系统
- 测试扩展到 SSE 全链路观察、`gpu_queued` 取消、终态重复取消、成功/失败 webhook、artifacts 接口行为，以及取消事件落库；当前 `.venv/bin/pytest tests -q` 结果为 `11 passed`
- 收口仓库卫生：新增 `.gitignore`，覆盖 `.venv/`、`__pycache__/`、SQLite、本地 mock artifacts、pytest/cache 等运行产物，避免本地验证噪音污染工作树
- 更新 `README.md` 为可交接版本，补齐安装、启动、测试、SSE / 成功链路 / 取消链路验证方式、主要 API 用法、mock 语义边界和 deferred 范围
- `serve.py` 新增低风险启动兼容层，支持在 `gen3d/` 仓库根目录直接执行 `python serve.py`，同时保留 `python -m gen3d.serve`
- 新增 `scripts/bench.py` 作为 Phase A 最小 smoke helper，可直接验证 success / cancel / events 三条基础链路
- 本轮完成后再次执行 `pytest tests -q`，结果仍为 `11 passed`

## Notes

- Phase A 不实现 Redis、Grafana、多机、Hunyuan3D
- TRELLIS2 官方：`microsoft/TRELLIS.2-4B`（HuggingFace）
- 本轮仍未接入真实 GPU、真实模型权重、MinIO；但 Phase A 所需的 mock 链路、SSE、取消、webhook、artifacts 查询已经打通
- `POST /v1/tasks` 当前会在后台自动跑完整条 mock 链路；Phase A 到本轮为止已完成，可直接交接给下一阶段继续接真实 provider / store / deployment
- 为兼容 `python -m gen3d.serve` 的包运行方式，测试通过在 `tests/` 内显式把工作区根目录加到 `sys.path`
- 当前 `AsyncGen3DEngine.stream_events()` 和 `PipelineCoordinator.add_listener()` 已被真实用于 SSE / webhook；下一轮若接更复杂消费者，仍可直接复用这条更新流
- 取消语义当前明确限定为 `gpu_queued` 可稳定取消；运行中阶段暂不承诺 step 级中断，后续若扩展 best-effort 取消，可继续沿 stage 边界插入检查
- `ArtifactStore` 目前落本地 mock 文件并返回 `mock://artifacts/...` 元数据，占位接口后续可无缝替换成 MinIO/presign
- 明确 deferred 到后续阶段的事项：
- 真实 TRELLIS2 权重加载、真实 GPU Worker 常驻模型、真实 GLB 导出
- MinIO / presigned URL / 真实 artifact store 接入
- Prometheus 指标、部署镜像、docker-compose、生产化发布流程
- 运行中阶段的复杂取消、webhook 重试与失败投递治理
- 多机 Worker、阶段解耦和更复杂的调度策略
