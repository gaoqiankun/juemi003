# gen3d AI Coder 执行指南

> 本文档是 gen3d 服务的 AI Coder 工作说明。开始任何开发前必须完整阅读本文档和规划文档。

---

## 0. 先读这些文件

```
gen3d/docs/PLAN.md     ← 完整架构规划，是本次实现的唯一设计基准
gen3d/AGENTS.md        ← 本文件，执行指南
gen3d/plan/            ← 历次规划日志，了解决策背景
```

**不要**根据自己的推断改变架构设计，一切以 `PLAN.md` 为准。有疑问先问，不要自己发明。
完成任务后更新对应 plan 文件，或新建 plan 文件，与代码一起提交。

---

## 1. 项目上下文

`gen3d` 是 hey3d 多仓工作区（`/Users/gqk/work/hey3d`）的子仓库，负责 3D 生成推理服务。

```
hey3d/
├── ios/        iOS 客户端（不要动）
├── server/     主后端 FastAPI + SQLite（不要动）
└── gen3d/      本仓库，当前只有 docs/，代码从零开始
```

**关键约束**：
- 根目录 `hey3d/` 不是 git 仓库，只在 `gen3d/` 内提交
- `gen3d/` 是独立 Python 项目，有自己的依赖和 Docker 镜像
- 不要修改 `ios/` 和 `server/` 的任何文件

---

## 2. 技术栈

| 层 | 技术 |
|---|---|
| API Server | FastAPI + uvicorn |
| 异步核心 | asyncio（单进程，多协程） |
| GPU Worker | multiprocessing（独立子进程，每 GPU 一个） |
| 任务持久化 | SQLite + aiosqlite |
| 产物存储 | MinIO（aiobotocore） |
| 配置管理 | pydantic-settings |
| 指标 | prometheus-client |
| 3D 推理 | TRELLIS2（`Trellis2ImageTo3DPipeline`），详见 PLAN.md §TRELLIS2 事实 |
| GLB 导出 | `o_voxel.postprocess.to_glb()` |
| Python 版本 | 3.12.7（本地通过 pyenv virtualenv `hey3d_gen3d` 管理） |

---

## 3. 目标文件结构

严格按照 `PLAN.md §11` 的文件结构创建，不要新增不在计划里的文件：

```
gen3d/
├── serve.py                        # 启动入口：python -m gen3d.serve
├── config.py                       # ServingConfig (pydantic-settings)
│
├── engine/
│   ├── async_engine.py             # AsyncGen3DEngine
│   ├── pipeline.py                 # PipelineCoordinator
│   └── sequence.py                 # RequestSequence（请求状态机）
│
├── stages/
│   ├── base.py                     # BaseStage 接口
│   ├── preprocess/
│   │   └── stage.py
│   ├── gpu/
│   │   ├── stage.py                # GPUStage（调度 + Worker 池）
│   │   ├── scheduler.py            # FlowMatchingScheduler
│   │   └── worker.py               # GPUWorker 子进程
│   └── export/
│       └── stage.py
│
├── model/
│   ├── base.py                     # BaseModelProvider Protocol
│   ├── trellis2/
│   │   └── provider.py             # Trellis2Provider
│   └── hunyuan3d/
│       └── provider.py             # 占位，暂不实现
│
├── api/
│   ├── server.py                   # FastAPI app
│   └── schemas.py                  # Pydantic 请求/响应模型
│
├── storage/
│   ├── task_store.py               # SQLite 读写
│   └── artifact_store.py           # MinIO 封装
│
├── observability/
│   └── metrics.py                  # Prometheus metrics
│
├── scripts/
│   ├── download_models.sh
│   └── bench.py
│
├── docker/
│   ├── Dockerfile.serve
│   └── Dockerfile.worker
│
├── deploy/
│   └── docker-compose.yml
│
├── tests/
│   ├── test_api.py
│   ├── test_pipeline.py
│   └── test_scheduler.py
│
├── requirements.txt                # 服务依赖（不含 GPU）
├── requirements-worker.txt         # Worker 依赖（含 torch + trellis2）
└── docs/
    ├── PLAN.md
    └── PLAN.bak.md
```

---

## 4. 实现顺序：Phase A 优先

**当前只实现 Phase A**（骨架 + Mock，不碰真实 GPU 推理）。

Phase A 目标：整个请求链路端到端跑通，GPU 推理用 sleep 模拟。

### Phase A 交付清单

- [ ] `config.py` — `ServingConfig`，读取环境变量
- [ ] `engine/sequence.py` — `RequestSequence` 状态机，所有状态枚举
- [ ] `storage/task_store.py` — SQLite 建表 + CRUD（aiosqlite）
- [ ] `storage/artifact_store.py` — MinIO 上传/presign（可用 mock 实现先跑通）
- [ ] `model/base.py` — `BaseModelProvider` Protocol + `StageProgress` + `GenerationResult`
- [ ] `model/trellis2/provider.py` — **MockTrellis2Provider**（sleep 模拟，不加载真实模型）
- [ ] `stages/preprocess/stage.py` — 图像下载 + PIL 解码（真实实现，httpx async）
- [ ] `stages/gpu/scheduler.py` — `FlowMatchingScheduler`（批次形成逻辑）
- [ ] `stages/gpu/worker.py` — `GPUWorker` 子进程（Phase A 用 MockProvider）
- [ ] `stages/gpu/stage.py` — `GPUStage`（Worker 进程池管理）
- [ ] `stages/export/stage.py` — `ExportStage`（Phase A：跳过 GLB 导出，直接写占位文件）
- [ ] `engine/pipeline.py` — `PipelineCoordinator`（串联三个 Stage）
- [ ] `engine/async_engine.py` — `AsyncGen3DEngine`（API 层包装）
- [ ] `api/schemas.py` — 请求/响应 Pydantic 模型
- [ ] `api/server.py` — FastAPI（所有端点：提交/查询/取消/SSE/下载）
- [ ] `serve.py` — 启动入口
- [ ] `deploy/docker-compose.yml` — MinIO + gen3d-serve（Phase A 无真实 GPU）
- [ ] `tests/test_api.py` — 基础 API 测试（httpx TestClient）
- [ ] `tests/test_scheduler.py` — 批次形成逻辑单测

---

## 5. 关键实现细节

### 5.1 RequestSequence 状态枚举

状态严格按 `PLAN.md §6` 定义：
```
submitted → preprocessing → gpu_queued → gpu_ss → gpu_shape → gpu_material
→ exporting → uploading → succeeded
                                     ↘ failed / cancelled（任意阶段可转入）
```

### 5.2 BaseModelProvider Protocol（重要）

`GPUWorker` 只依赖此接口，不直接 import trellis2：

```python
# model/base.py
from dataclasses import dataclass, field
from typing import Protocol
from PIL import Image

@dataclass
class StageProgress:
    stage_name: str      # "ss" / "shape" / "material"
    step: int
    total_steps: int

@dataclass
class GenerationResult:
    mesh: object         # 模型内部 mesh 对象，ExportStage 转 GLB
    metadata: dict = field(default_factory=dict)

class BaseModelProvider(Protocol):

    @classmethod
    def from_pretrained(cls, model_path: str) -> "BaseModelProvider": ...

    def estimate_vram_mb(self, batch_size: int, options: dict) -> int: ...

    @property
    def stages(self) -> list[dict]:
        """[{"name":"ss","weight":0.20},{"name":"shape","weight":0.45},{"name":"material","weight":0.35}]"""
        ...

    async def run_batch(
        self,
        images: list[Image.Image],
        options: dict,
        progress_cb=None,     # Callable[[StageProgress], None]
        cancel_flags=None,    # list[bool]
    ) -> list[GenerationResult]: ...

    def export_glb(self, result: GenerationResult, output_path: str, options: dict) -> None: ...
```

### 5.3 MockTrellis2Provider（Phase A）

```python
# model/trellis2/provider.py （Phase A mock）
import asyncio
from model.base import StageProgress, GenerationResult
from PIL import Image

class MockTrellis2Provider:

    @classmethod
    def from_pretrained(cls, model_path: str) -> "MockTrellis2Provider":
        return cls()

    def estimate_vram_mb(self, batch_size: int, options: dict) -> int:
        return batch_size * 20_000

    @property
    def stages(self) -> list[dict]:
        return [
            {"name": "ss",       "weight": 0.20},
            {"name": "shape",    "weight": 0.45},
            {"name": "material", "weight": 0.35},
        ]

    async def run_batch(self, images, options, progress_cb=None, cancel_flags=None):
        # 模拟三阶段，总耗时约 3 秒（Phase A mock）
        stage_steps = [
            ("ss",       options.get("ss_steps", 12),       0.5),
            ("shape",    options.get("shape_steps", 20),    1.5),
            ("material", options.get("material_steps", 12), 1.0),
        ]
        for stage_name, total_steps, sleep_sec in stage_steps:
            await asyncio.sleep(sleep_sec)
            if progress_cb:
                progress_cb(StageProgress(stage_name=stage_name, step=total_steps, total_steps=total_steps))
        return [GenerationResult(mesh=None, metadata={"mock": True}) for _ in images]

    def export_glb(self, result: GenerationResult, output_path: str, options: dict) -> None:
        # Phase A：写空文件占位
        with open(output_path, "wb") as f:
            f.write(b"MOCK_GLB")
```

### 5.4 FlowMatchingScheduler（批次形成）

- Request-level batching（不是 iteration-level）
- 等到满足 `max_batch_size` 或超过 `max_queue_delay_ms`，取出一批
- 送给空闲的 `GPUWorker`

```python
# 核心逻辑伪码
async def collect_batch(self) -> list[RequestSequence]:
    batch = []
    deadline = asyncio.get_event_loop().time() + self.max_queue_delay_ms / 1000
    while len(batch) < self.max_batch_size:
        timeout = deadline - asyncio.get_event_loop().time()
        if timeout <= 0:
            break
        try:
            seq = await asyncio.wait_for(self.queue.get(), timeout=timeout)
            batch.append(seq)
        except asyncio.TimeoutError:
            break
    return batch
```

### 5.5 GPUWorker 进程通信

- 每个 `GPUWorker` 是独立子进程（`multiprocessing.Process`）
- 主进程与 Worker 通过 `multiprocessing.Queue` 传递任务和结果
- Worker 启动时加载 provider（Phase A：MockProvider，不加载真实模型）
- 进度通过 Queue 回传 `StageProgress` 事件

### 5.6 API 端点

严格实现 `PLAN.md §8` 定义的接口：

```
POST   /v1/tasks                  # 提交任务
GET    /v1/tasks/{id}             # 查询状态
GET    /v1/tasks/{id}/events      # SSE 进度（EventSourceResponse）
POST   /v1/tasks/{id}/cancel      # 取消
GET    /v1/tasks/{id}/artifacts   # 获取 presigned URL
GET    /health
GET    /ready
GET    /metrics                   # Prometheus text 格式
```

鉴权：`Authorization: Bearer <INTERNAL_API_KEY>`，所有任务接口都需要。

### 5.7 SQLite Schema

严格按 `PLAN.md §9` 建表：
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'submitted',
    type TEXT NOT NULL DEFAULT 'image_to_3d',
    input_url TEXT,
    options_json TEXT,
    idempotency_key TEXT UNIQUE,
    callback_url TEXT,
    output_artifacts_json TEXT,
    error_message TEXT,
    failed_stage TEXT,
    retry_count INTEGER DEFAULT 0,
    assigned_worker_id TEXT,
    current_stage TEXT,
    created_at TEXT,
    queued_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);
```

### 5.8 Webhook 回调

任务完成（succeeded/failed）后，若 `callback_url` 非空，用 httpx 异步 POST：
```json
{
  "taskId": "...",
  "status": "succeeded",
  "artifacts": [{"type": "glb", "url": "...", "expires_at": "..."}],
  "error": null
}
```
失败重试 3 次，指数退避，最终失败只记录日志不抛异常。

### 5.9 ServingConfig 关键字段

```python
class ServingConfig(BaseSettings):
    # 模型
    model_provider: str = "trellis2"   # "trellis2" | "hunyuan3d"
    model_path: str = "/models/trellis2"
    mock_provider: bool = False        # True = 用 MockProvider，不加载真实权重

    # GPU
    gpu_ids: list[int] = [0]           # 每个 id 一个 Worker 进程
    max_batch_size: int = 1
    max_queue_delay_ms: int = 5000

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 18001
    internal_api_key: str = "changeme"

    # SQLite
    db_path: str = "storage/db/gen3d.sqlite3"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "gen3d-artifacts"
    minio_use_ssl: bool = False

    # 任务
    task_timeout_seconds: int = 600
    artifact_expiry_seconds: int = 86400
```

---

## 6. 编码规范

1. **类型注解**：所有函数、方法必须有类型注解（参数 + 返回值）
2. **异步优先**：IO 操作全部用 async/await，不要在 asyncio 线程里做同步阻塞 IO
3. **错误处理**：所有外部调用（httpx、MinIO、SQLite）都要捕获异常并更新任务状态
4. **日志**：用 `logging` 标准库，格式 `%(asctime)s %(name)s %(levelname)s %(message)s`，不要用 print
5. **配置**：所有可配置项通过 `ServingConfig` 读取，不要硬编码
6. **单一职责**：每个类只做一件事，不要把多个 Stage 逻辑混在一起
7. **不要过度设计**：Phase A 里不需要实现 Phase D 的功能（阶段解耦、多机等）

---

## 7. 测试要求

Phase A 至少覆盖：
- `test_api.py`：提交任务 → 轮询到 succeeded 的完整流程（用 TestClient + MockProvider）
- `test_scheduler.py`：批次形成逻辑（max_batch_size 满了提前触发，超时也触发）
- `test_pipeline.py`：状态机流转（submitted → … → succeeded / failed）

用 `pytest` + `pytest-asyncio`，不需要真实 GPU。

---

## 8. 不要实现的内容（Phase A 排除）

- 真实 TRELLIS2 权重加载（`Trellis2ImageTo3DPipeline`）——Phase B 实现
- 真实 GLB 导出（`o_voxel.postprocess.to_glb()`）——Phase B 实现
- ETA 跨阶段精准计算——Phase B 实现（Phase A 返回固定估算即可）
- Grafana 看板——Phase C 实现
- 阶段解耦（SS+Shape 与 Material 分 GPU 池）——Phase D 实现
- 多机 Worker（zmq/gRPC）——Phase D 实现
- Hunyuan3D Provider 实现——占位文件即可
- Redis——Phase A/B 不需要

---

## 9. 本地启动（Phase A）

```bash
# 1. 进入仓库
cd gen3d

# 2. 准备 pyenv 环境（首次一次性）
pyenv virtualenv 3.12.7 hey3d_gen3d
pyenv local hey3d_gen3d
python -m pip install -r requirements.txt

# 3. 启动 mock 服务（当前 Phase A 不需要 GPU / 不需要模型权重 / 不需要 MinIO）
INTERNAL_API_KEY=dev python serve.py

# 4. 验证
curl -H "Authorization: Bearer dev" \
     -H "Content-Type: application/json" \
     -d '{"type":"image_to_3d","image_url":"https://example.com/a.png"}' \
     http://localhost:18001/v1/tasks

# 5. 跑测试
python -m pytest tests/ -v
```

---

## 10. 提交规范

- 只在 `gen3d/` 目录内提交，不要动其他子仓库
- Commit message 格式：`<type>: <描述>`（feat / fix / refactor / test / docs / chore）
- 每完成一个 Phase A 的交付项就可以提交，不要等全部完成再一次性提交
- 提交前运行 `pytest tests/` 确保通过

---

## 11. 验收标准（Phase A）

以下全部通过才算 Phase A 完成：

1. `pytest tests/` 全绿
2. `MOCK_PROVIDER=true python -m gen3d.serve` 启动无报错
3. 提交一个任务，状态从 `submitted` 依次流转到 `succeeded`
4. SSE `/v1/tasks/{id}/events` 能收到 ss / shape / material 三个阶段事件
5. `GET /v1/tasks/{id}/artifacts` 返回 presigned URL（Phase A：MinIO 中有占位 GLB）
6. 取消一个 `gpu_queued` 状态的任务，状态变为 `cancelled`
7. `GET /metrics` 返回 Prometheus 格式指标

---

## 参考资料

- 架构规划：`gen3d/docs/PLAN.md`（必读）
- TRELLIS2 官方：`microsoft/TRELLIS.2-4B`（HuggingFace）
- vLLM Omni 参考：https://github.com/vllm-project/vllm（架构思路，不直接依赖）
- hey3d 整体项目：`/Users/gqk/work/hey3d/AGENTS.md`
