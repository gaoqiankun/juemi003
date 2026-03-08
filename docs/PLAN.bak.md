# gen3d 推理内核优先规划（V2）

## 1. 核心目标
`gen3d` 第一目标不是“平台壳”，而是先做成一个可压测、可扩容的 TRELLIS2 高并发推理服务。

- 目标结果：单模型常驻、动态批处理、稳定队列、可取消、可观测。
- 设计口径：
  - 模型正确性只参考 TRELLIS2 官方实现与权重。
  - 服务并发调度参考 vLLM 思路（continuous batching）。
  - 批处理参数设计参考 Triton 的 dynamic batching 经验。

## 2. 范围与优先级
### 2.1 V1 必做（只做 TRELLIS2）
1. 常驻推理进程（每 GPU 一进程，启动一次加载权重）。
2. 高并发调度器（连续批处理 + 动态微批）。
3. 异步任务 API（提交、状态、取消、结果下载）。
4. 实时队列信息（queuePosition、estimatedWaitSeconds、estimatedFinishAt）。
5. 基础部署与压测脚本（单机多卡）。

### 2.2 暂缓项
1. 多模型路由策略（Hunyuan/商业 API）先不做。
2. 复杂权限体系和多租户计费先不做。
3. 工作流编排 UI 先不做。

## 3. 关键架构（推理内核）
### 3.1 组件
1. `api-gateway`（薄层）
  - 参数校验、任务入队、状态查询、取消任务、签名下载链接。
2. `scheduler`（核心）
  - 维护等待队列、运行队列、超时与取消。
  - 按 GPU 可用 slot 进行连续批处理调度。
3. `gpu-worker`（核心）
  - 模型常驻显存，循环执行分阶段推理。
  - 支持批内逐请求进度回传和中断。
4. `postprocess-pool`
  - mesh 导出/压缩/上传异步化，避免占用 GPU。
5. `state-store`
  - Redis：队列与实时状态。
  - PostgreSQL：任务元数据、事件、审计。
  - MinIO/S3：结果产物。

### 3.2 数据流
1. `POST /tasks` -> 入队（返回 taskId）。
2. scheduler 聚合请求 -> 形成微批 -> 下发 gpu-worker。
3. worker 回传阶段进度（shape/texture/export）。
4. 后处理池上传产物 -> 任务完成。
5. 客户端通过 `GET /tasks/{id}` 或 SSE 拉取状态。

## 4. 并发设计（核心细节）
### 4.1 连续批处理
1. scheduler 按 `max_batch_size` 与 `max_queue_delay_ms` 组批。
2. 每轮迭代结束可插入新请求，不等整批完成才接纳。
3. 新请求若超出显存预算，留在队列等待下一轮。

### 4.2 显存与并发控制
1. 每 worker 维护 `vram_budget_mb`、`max_concurrent_requests`。
2. 请求入批前做显存预估（输入分辨率、step、guidance 相关）。
3. 超预算触发 backpressure，不盲目扩批。

### 4.3 取消、超时、重试
1. `queued` 任务可立即取消并从队列删除。
2. `running` 任务设置 cancel 标志，在阶段边界安全中断。
3. 超时进入 `failed(timeout)`，可按策略自动重试一次。

### 4.4 ETA 估算
1. 维护最近 N 个成功任务耗时窗口（按模型+任务类型）。
2. 返回 `estimatedWaitSeconds` 与 `estimatedFinishAt`。
3. 每次队列变动或任务完成后重算 ETA。

## 5. TRELLIS2 执行策略
### 5.1 输入模式
1. V1 先支持 `image_to_3d`。
2. `text_to_3d` 作为 V1.5：`text -> image`（独立 t2i 进程）-> TRELLIS2。

### 5.2 执行分阶段
1. `preprocess`：图像规范化、背景处理（可选）。
2. `shape`：主干几何生成（GPU）。
3. `texture`：纹理生成（GPU，按参数可选）。
4. `export`：GLB/OBJ 导出与上传（CPU）。

### 5.3 进度定义（统一给客户端）
1. `queued`：0%
2. `preprocess`：1-10%
3. `shape`：11-70%
4. `texture`：71-90%
5. `export`：91-99%
6. `succeeded`：100%

## 6. API 只保留最小集合
1. `POST /v1/tasks`
2. `GET /v1/tasks/{id}`
3. `GET /v1/tasks/{id}/events`（SSE）
4. `POST /v1/tasks/{id}/cancel`
5. `GET /v1/tasks/{id}/artifacts`

### 6.1 状态返回字段（固定）
- `taskId`
- `status`
- `progress`
- `currentStage`
- `queuePosition`
- `estimatedWaitSeconds`
- `estimatedFinishAt`
- `createdAt`
- `startedAt`
- `updatedAt`
- `error`
- `artifacts`

## 7. 部署策略（先单机多卡）
### 7.1 进程拓扑
1. `api` 1-2 副本（CPU）。
2. `scheduler` 1 副本（CPU）。
3. `worker` 每 GPU 1 副本（CUDA_VISIBLE_DEVICES 绑定）。
4. `postprocess` 2-4 线程池（CPU）。

### 7.2 启动顺序
1. 启 Redis/PostgreSQL/MinIO。
2. 启 worker 并完成模型预热。
3. 启 scheduler。
4. 启 api 并开放流量。

### 7.3 容器化
1. `docker-compose` 用于单机验证和压测。
2. 后续迁移 `K8s + HPA + node selector`。

## 8. 指标与压测（验收核心）
### 8.1 必备指标
1. `queue_depth`
2. `queue_wait_seconds`（P50/P90/P99）
3. `task_total_latency_seconds`（P50/P90/P99）
4. `tasks_completed_per_minute`
5. `gpu_utilization`、`gpu_memory_used`
6. `task_failure_rate`
7. `cancel_effective_rate`

### 8.2 首版验收门槛
1. 稳态并发下 GPU 利用率 >= 70%。
2. 队列 ETA 相对误差（P90）<= 30%。
3. 任务成功率 >= 95%（剔除非法输入）。
4. 提交后 1 秒内可查询到可用状态。

## 9. 里程碑（以推理内核为主线）
### Phase A（1 周）: 跑通内核
1. TRELLIS2 常驻 worker。
2. scheduler + 单队列 + 微批。
3. 基础任务状态机与 artifacts 输出。

### Phase B（1 周）: 并发能力成型
1. 连续批处理 + backpressure。
2. 取消/超时/重试。
3. ETA 估算与 SSE 状态流。

### Phase C（1 周）: 稳定性与性能
1. 压测脚本（固定输入集）。
2. 显存碎片与吞吐优化（批大小、等待窗口、阶段并行）。
3. 告警规则与故障恢复手册。

### Phase D（后续）: 扩展能力
1. text_to_3d 桥接链路。
2. 第二模型接入（Hunyuan2.1/商业 API）。
3. 路由策略（speed/quality/cost）。

## 10. 当前立刻执行清单
1. 锁定 V1 只做 TRELLIS2 `image_to_3d` 高并发内核。
2. 定义 scheduler 参数：
  - `max_batch_size`
  - `max_queue_delay_ms`
  - `vram_budget_mb`
  - `max_concurrent_requests`
3. 产出 3 个核心模块：
  - `engine/scheduler.py`
  - `engine/runner_trellis2.py`
  - `engine/worker.py`
4. 产出压测基线：
  - 固定输入集
  - 并发阶梯（10/20/50/...）
  - 指标看板与门槛
