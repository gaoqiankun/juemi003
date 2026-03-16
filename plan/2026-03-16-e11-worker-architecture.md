# E11 · Worker 架构重设计：API 解耦 + 多模型 + ETA
Date / Status: 2026-03-16 / done / Commits: n/a

## Goal
将 API 层与模型层完全解耦，任意时刻用户都可提交/查询任务；
引入 ModelRegistry 管理多模型生命周期；保证 FIFO 处理顺序；
基于 per-stage 运行统计为用户提供可靠的预计等待时间。

## Key Decisions

### 1. API 与 Worker 完全解耦

```
用户
 ↓ POST /v1/tasks（任意时刻，立即 201）
API 层（永远可用，不依赖模型）
 ↓ 写 DB（status=queued）
DB（tasks 表）
 ↑ Worker poll + event
Worker Pool（N 个并发 worker）
 ↓ 按 task.model 调用
ModelRegistry
 ├── trellis（loading | ready | error）
 └── future_model（...）
```

- API 层不知道、不关心模型状态，只负责 task CRUD
- Worker 失败/重启不影响 API 可用性
- 现阶段 API + Worker 同进程，接口边界通过 DB 隔离，未来可拆分

### 2. ModelRegistry

- 每个模型独立状态：`not_loaded | loading | ready | error`
- 每个模型一个 `asyncio.Event`，加载完成后 `set()`
- Worker 调用 `await registry.wait_ready(model_name)` 等待模型就绪
- 模型**按需懒加载**：首次有该类型任务入队时触发加载，不在启动时阻塞
- 加载失败的任务：状态置 `failed`，error_message 说明模型加载失败，不影响其他任务

### 3. task.model 字段

- tasks 表新增 `model TEXT NOT NULL DEFAULT 'trellis'`，auto-migration
- POST /v1/tasks body 新增可选 `model` 字段（默认 `trellis`）
- Worker 根据 `task.model` 从 ModelRegistry 获取对应实例

### 4. FIFO + 原子 claim（防竞态）

Worker 取任务使用乐观锁，两步原子操作：

```sql
-- Step 1: 找最早入队且目标模型已 ready（或正在加载）的任务
SELECT id FROM tasks
WHERE status = 'queued'
ORDER BY queued_at ASC
LIMIT 1

-- Step 2: 原子 claim，CAS 防止多 Worker 重复取同一任务
UPDATE tasks
SET status = 'processing', assigned_worker_id = ?
WHERE id = ? AND status = 'queued'
```

UPDATE 影响行数 = 0 则重试，保证严格 FIFO、无重复处理。

### 5. per-stage ETA 统计（Welford 在线算法）

新增 `stage_stats` 表，每个 (model, stage) 维护运行均值和方差：

| 列 | 说明 |
|----|------|
| `model_name` | 模型名，如 trellis |
| `stage_name` | 阶段名，如 sparse_structure |
| `count` | 样本数 |
| `mean_seconds` | 均值（Welford 实时更新）|
| `m2_seconds` | 方差分子（Welford 用）|

每个阶段完成时 Worker O(1) 更新对应行，不存全量历史。

**ETA 计算（查询时动态计算，不存储）：**

- `queued` 状态：`eta = ceil(queue_position / parallel_slots) × Σ mean(all stages)`
- `processing` 状态：`eta = mean(current_stage) × (1 - progress/100) + Σ mean(remaining stages)`
- 不同模型查各自的 `stage_stats`，天然隔离
- 置信区间：`±1.96 × √(Σ variance)`，供前端显示"约 3~5 分钟"

DB 已有 `queue_position`、`estimated_wait_seconds`、`estimated_finish_at` 字段，
本次补全计算逻辑并在 GET /v1/tasks/{id} 响应中正确填充。

### 6. /health 和 /readiness

| 端点 | 用途 | 返回条件 |
|------|------|---------|
| `GET /health` | 进程存活（liveness） | 永远 200 |
| `GET /readiness` | 流量就绪（运维用） | 至少一个 Worker 运行且有模型 ready → 200，否则 503 |

`/readiness` 不暴露给用户，供 Docker HEALTHCHECK / nginx upstream 使用。

### 7. upload-only 输入（补齐之前的待办）

- POST /v1/tasks：`input_url` 只接受 `upload://` 格式，其他返回 400
- GET /v1/tasks / GET /v1/tasks/{id}：响应包含 `input_url` 字段
- DELETE /v1/tasks/{id} cleanup worker：清理 artifact 同时删除对应 upload 文件
  - `input_url` 为 `upload://hash` → 删 `UPLOADS_DIR/{hash}.*`
  - `input_url` 为其他格式 → 不处理

## Changes

| 文件 | 变更说明 |
|------|---------|
| `engine/model_registry.py` | 新增 ModelRegistry：per-model 状态机 + asyncio.Event + 懒加载 |
| `engine/async_engine.py` | Worker loop 改为 DB poll + atomic claim；查询时动态补 queue_position / ETA；cleanup 同时删除 upload 源文件 |
| `engine/pipeline.py` | PipelineCoordinator 改为阶段执行器 + recovery，不再维护进程内任务队列 |
| `engine/sequence.py` | 新增 `model` 字段；初始状态改为 `queued` |
| `storage/task_store.py` | tasks 表加 `model` 列；新增 `stage_stats` 表；补 claim/requeue/queue_position/stage_stats 读写与 auto-migration |
| `stages/preprocess/stage.py` | preprocessing 完成后写入 stage_stats |
| `stages/gpu/stage.py` | GPU 阶段改为从 ModelRegistry 获取 runtime；每个 GPU 子阶段完成后写入 stage_stats |
| `stages/export/stage.py` | exporting / uploading 分别写入 stage_stats；export 阶段从 ModelRegistry 取 provider |
| `api/server.py` | create_app 改为懒加载模型；POST /v1/tasks 改为 upload-only；新增 `/readiness`；保留 `/ready` 兼容别名 |
| `api/schemas.py` | TaskCreateRequest 增加 `input_url` / `model`；Task list/detail 响应增加 `input_url` / `model` |
| `tests/test_api.py` / `tests/test_pipeline.py` | 覆盖 readiness、upload-only、FIFO、动态 ETA、upload cleanup、lazy load 失败降级等验收场景 |

## Notes

- stage_stats 冷启动时无历史数据，ETA 返回 null，不影响功能
- 现阶段 parallel_slots = `len(GPU_DEVICE_IDS)`，Worker 数量与 GPU slot 数一致
- 模型加载错误不 crash 服务，task 状态置 failed + 错误信息
- Worker 与 API 同进程，通过 DB 解耦；未来拆分只需改 Worker 的任务来源
- upload 文件扩展名：从 UPLOADS_DIR 里 glob `{hash}.*` 匹配，不假定后缀
- 验证结果：`python -m pytest tests -q` → `64 passed`
