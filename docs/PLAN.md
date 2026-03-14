# gen3d 规划 V3 — vLLM Omni 启发的阶段解耦推理服务

> 最后更新：基于 TRELLIS2 官方推理实现校准

---

## TRELLIS2 官方推理事实（设计基线）

在规划任何架构前，先对齐 TRELLIS2 的实际推理方式：

### 官方 Pipeline

```python
from trellis2.pipelines import Trellis2ImageTo3DPipeline

pipeline = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
pipeline.cuda()

mesh = pipeline.run(
    image,
    resolution=1024,
    sparse_structure_sampler_params={'steps': 12, 'guidance_scale': 7.5},
    shape_sampler_params=          {'steps': 20, 'guidance_scale': 7.5},
    material_sampler_params=       {'steps': 12, 'guidance_scale': 3.0},
)[0]

# GLB 导出（CPU，独立步骤）
o_voxel.postprocess.to_glb(mesh, output_path="output.glb", ...)
```

### 实际三阶段结构

| 阶段 | 内部名称 | 模型 | 默认步数 | 占总 GPU 时间 |
|---|---|---|---|---|
| 1 | Sparse Structure (SS) | Flow Matching Transformer | 12 步 | } |
| 2 | Shape (Geometry) | Flow Matching Transformer | 20 步 | } 60–65% |
| 3 | Material (PBR) | Flow Matching Transformer | 12 步 | 35–40% |

> **注**：使用 Flow Matching，不是 DDPM。步数默认 12/20/12，不是 50/50。
> 三个阶段在 `Trellis2ImageTo3DPipeline.run()` 内部串行，共享同一 GPU。

### 实际速度（官方测试）

| 分辨率 | H100 | A100（估算）| RTX 4090（估算）|
|---|---|---|---|
| 512³ | ~3 s | ~5 s | ~10 s |
| 1024³ | **~17 s** | **~25 s** | **~60 s** |
| 1536³ | ~60 s | ~90 s | ~4 min |

> 单任务端到端（含 Export）：H100 约 25s，RTX 4090 约 70s。
> **不是 5-15 分钟**——之前的预估是基于错误假设。

### 显存要求

- 最低 24GB VRAM（官方）
- 官方测试 GPU：A100 40GB / H100 80GB
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 可减少碎片

---

## 核心设计思路

参考 vLLM Omni（Fully Disaggregated Pipeline）架构思想，自行实现轻量版：
- **不直接依赖 vLLM Omni**，借鉴其阶段解耦和调度模式
- **Phase A/B 用数据并行**：每 GPU 运行完整 TRELLIS2 pipeline，不拆分阶段
- **Phase D 再做阶段解耦**：在 SS/Shape 与 Material 间切分，实现真正的级间并行
- **核心收益（当前）**：多 GPU 数据并行，多请求同时推理

---

## 1. 为什么要阶段解耦（阶段并行原理）

TRELLIS2 GPU 推理结束后，还有 CPU-bound 的 Export（GLB 导出 + 上传）：

```
阶段：  [Preprocess] → [GPU Pipeline: SS→Shape→Material] → [Export+Upload]
资源：      CPU               GPU（~17-60s）                    CPU
```

数据并行 + 阶段并行后：
```
时间轴 →
GPU 0:   [Req1 全流程] [Req3 全流程] [Req5 全流程] ...
GPU 1:   [Req2 全流程] [Req4 全流程] [Req6 全流程] ...
Export:              [Req1 导出]  [Req2 导出]  [Req3 导出] ...
```

GPU 执行时 CPU 同步做上一批的导出，GPU 几乎不等 CPU。

---

## 2. 整体架构

```
HTTP 请求 (server 调用)
        │
        ▼
┌──────────────────────────────────────────────────────┐
│                   gen3d Serving                       │
│                                                        │
│  ┌────────────────────────────────────────────────┐   │
│  │            API Server (FastAPI)                │   │
│  │  - 提交任务、查询状态、取消、SSE 进度、下载    │   │
│  └───────────────────┬────────────────────────────┘   │
│                       │                               │
│  ┌────────────────────▼────────────────────────────┐  │
│  │          AsyncGen3DEngine                        │  │
│  │  - 异步包装层（类比 vLLM AsyncLLMEngine）       │  │
│  │  - 管理请求生命周期，SSE/Webhook 回调           │  │
│  └───────────────────┬────────────────────────────┘   │
│                       │ asyncio queue                 │
│  ┌────────────────────▼────────────────────────────┐  │
│  │          PipelineCoordinator                     │  │
│  │  - 路由请求在各阶段之间流转                     │  │
│  │  - 汇总阶段进度，触发状态更新                   │  │
│  └──────┬───────────────────────┬───────────────────┘  │
│         │                       │                      │
│  ┌──────▼──────┐      ┌─────────▼──────────────────┐  │
│  │PreprocessStage│    │      GPUStage               │  │
│  │   (CPU)      │    │  (数据并行，每 GPU 一 Worker) │  │
│  │ 图像解码     │    │                               │  │
│  │ 归一化       │    │  Worker-0 (GPU 0):            │  │
│  │ 背景处理     │    │   Trellis2Pipeline.run()      │  │
│  └──────────────┘    │  Worker-1 (GPU 1):            │  │
│                       │   Trellis2Pipeline.run()      │  │
│                       │  Worker-N (GPU N): ...        │  │
│                       └───────────────┬───────────────┘  │
│                                       │                   │
│                              ┌────────▼──────────┐        │
│                              │   ExportStage      │        │
│                              │   (CPU 线程池)     │        │
│                              │   o_voxel.to_glb() │        │
│                              │   MinIO 上传        │        │
│                              └───────────────────┘        │
│                                                            │
│  ┌─────────────────────────────────────────────────────┐  │
│  │       SQLite (任务持久化) + MinIO (产物存储)        │  │
│  └─────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 各组件设计

### 3.1 API Server（`api/`）
- FastAPI，与 AsyncGen3DEngine 共享 asyncio loop
- Bearer token 鉴权（内部单 key，预留多 key 扩展）
- SSE endpoint 通过 asyncio.Queue 推送进度
- MinIO presigned URL 生成

### 3.2 AsyncGen3DEngine（`engine/async_engine.py`）
- 对 API Server 暴露 async 接口：`submit`, `cancel`, `stream_events`
- 内部与 PipelineCoordinator 通过 asyncio 队列通信
- 维护 `task_id → asyncio.Queue` 映射，用于 SSE 推送
- 任务完成后触发 Webhook callback（如配置了 `callback_url`）

### 3.3 PipelineCoordinator（`engine/pipeline.py`）
- 独立 asyncio 任务（同进程内）
- Preprocess 完成 → 送入 GPUStage 队列
- GPU 完成 → 送入 ExportStage 队列
- Export 完成 → 任务标记 succeeded，触发回调

### 3.4 RequestSequence（`engine/sequence.py`）
- 每个请求的内存状态对象
- 持有：task_id、当前状态、当前阶段 step、latent 中间结果（GPU→Export 传递）
- 状态流转见第 6 节

### 3.5 GPUStage（`stages/gpu/`）
核心执行阶段，类比 vLLM Omni 的 `GPUGenerationWorker`：

```
GPUStage 内部：
  ┌──────────────────────────────────┐
  │  FlowMatchingScheduler           │  ← 批次形成
  │  - waiting_queue                 │    max_batch_size + max_wait_ms
  │  - VRAM 预算检查（24GB 基准）    │
  └──────────────┬───────────────────┘
                 │ 分发 batch 给空闲 Worker
  ┌──────────────▼───────────────────┐
  │  GPUWorker 进程池                │  ← 每 GPU 一个独立进程
  │  Worker-0 (CUDA_VISIBLE_DEVICES=0)│   常驻 Trellis2ImageTo3DPipeline
  │  Worker-1 (CUDA_VISIBLE_DEVICES=1)│   run() 完成后回传 mesh latent
  │  ...                             │
  └──────────────────────────────────┘
```

**FlowMatchingScheduler 逻辑**（request-level batching）：
```python
while True:
    # 等待 max_wait_ms 或凑满 max_batch_size
    batch = await collect_batch()

    # 找一个空闲的 GPUWorker
    worker = await worker_pool.acquire()

    # 异步执行（非阻塞，等 worker 返回结果）
    results = await worker.run_batch(batch, progress_cb=report_progress)

    # 结果送 ExportStage
    for seq, mesh in zip(batch, results):
        seq.mesh = mesh
        export_queue.put(seq)

    worker_pool.release(worker)
```

**GPUWorker（独立子进程，`stages/gpu/worker.py`）**：
- 启动时加载 `Trellis2ImageTo3DPipeline`（常驻显存）
- 接收 batch 的图像列表，返回 mesh latent 列表
- 阶段内进度回传：利用 pipeline 的 callback hook（SS/Shape/Material 各阶段完成时）
- 支持 cancel 检查（在阶段边界，不是 step 边界）
- SIGTERM → 完成当前 batch → 退出

### 3.5.1 Model Provider 抽象层（`model/base.py`）

GPUWorker 不直接依赖 TRELLIS2，面向 `BaseModelProvider` 接口编程，方便后续换模型：

```python
from dataclasses import dataclass
from typing import Protocol, AsyncIterator
from PIL import Image

@dataclass
class StageProgress:
    stage_name: str      # "ss" / "shape" / "material"（各模型自定义）
    step: int
    total_steps: int

@dataclass
class GenerationResult:
    mesh: any            # 模型内部 mesh 对象，ExportStage 负责转 GLB
    metadata: dict

class BaseModelProvider(Protocol):

    @classmethod
    def from_pretrained(cls, model_path: str) -> "BaseModelProvider": ...

    def estimate_vram_mb(self, batch_size: int, options: dict) -> int:
        """VRAM 估算，供 Scheduler 准入控制用。"""
        ...

    @property
    def stages(self) -> list[dict]:
        """声明阶段列表和权重，供进度映射。
        示例：[{"name":"ss","weight":0.20},{"name":"shape","weight":0.45},...]
        """
        ...

    async def run_batch(
        self,
        images: list[Image.Image],
        options: dict,
        progress_cb=None,        # 每阶段完成时回调 StageProgress
        cancel_flags=None,       # 每请求一个 bool，True 表示取消
    ) -> list[GenerationResult]: ...

    def export_glb(self, result: GenerationResult, output_path: str, options: dict) -> None:
        """导出 GLB（在 ExportStage 的线程池内调用）。"""
        ...
```

**TRELLIS2 实现**（`model/trellis2/provider.py`）：
- 封装官方 `Trellis2ImageTo3DPipeline`
- `export_glb` 调用 `o_voxel.postprocess.to_glb()`
- `estimate_vram_mb`：按分辨率返回经验值 + 20% 裕量

**未来换混元 3D**（`model/hunyuan3d/provider.py`）：
- 实现同一接口，GPUWorker / Scheduler 代码无需改动

**配置切换**（`config.py`）：
```python
class ServingConfig(BaseSettings):
    model_provider: str = "trellis2"   # "trellis2" | "hunyuan3d" | ...
    model_path: str = "/models/trellis2"
```

---

### 3.6 PreprocessStage（`stages/preprocess/stage.py`）
- asyncio 协程（CPU，不开子进程）
- 图像下载（httpx async）→ 解码 → 归一化 → 可选背景移除
- 完成后送入 GPUStage 的 waiting_queue

### 3.7 ExportStage（`stages/export/stage.py`）
- `ThreadPoolExecutor`（CPU，阻塞调用 o_voxel，不能放 asyncio）
- `o_voxel.postprocess.to_glb(mesh, decimation_target=1_000_000, texture_size=4096)`
- MinIO 上传（带 3 次重试，指数退避）
- 上传完成后：更新 DB 为 succeeded，触发 Webhook

---

## 4. GPU 分配策略

### 单机多卡（Phase A/B 采用数据并行）

每个 GPU 加载完整 TRELLIS2 pipeline，独立处理不同请求：

```bash
python -m gen3d.serve \
  --model /models/trellis2 \
  --gpus 0,1,2,3 \           # 所有 GPU 均作为完整 pipeline worker
  --max-batch-size 2 \       # 每 GPU 每次处理 2 个请求（24GB VRAM 约束）
  --port 18001
```

```yaml
# docker-compose.yml
services:
  gen3d-serve:
    image: gen3d-worker:latest
    runtime: nvidia
    environment:
      CUDA_VISIBLE_DEVICES: "0,1,2,3"
      MODEL_PATH: /models/trellis2
      MAX_BATCH_SIZE: "2"
    volumes:
      - /data/models:/models:ro
```

### 资源估算（1024³，单 GPU）

| GPU | 单任务时间 | 批大小 2 时间 | 每小时吞吐 |
|---|---|---|---|
| H100 | ~17s | ~25s | ~288 任务 |
| A100 | ~25s | ~35s | ~206 任务 |
| RTX 4090 | ~60s | ~85s | ~85 任务 |

> 4 张 A100 → 每小时约 800 任务。

### Phase D：阶段解耦（GPU 级别）

拆分 SS+Shape 与 Material 到不同 GPU 池，实现级间流水线并行：
```bash
python -m gen3d.serve \
  --model /models/trellis2 \
  --geometry-gpus 0,1 \      # 只跑 SS + Shape
  --material-gpus 2,3 \      # 只跑 Material
  --port 18001
```
此模式需要修改 TRELLIS2 pipeline 内部，切分模型加载，Phase D 实现。

---

## 5. 模型权重管理

- 宿主机预下载到 `/data/models/trellis2/`（从 HuggingFace 拉取）
- Volume 只读挂载进容器（`:ro`）
- GPUWorker 启动时调用 `Trellis2ImageTo3DPipeline.from_pretrained(MODEL_PATH)`
- 路径不存在则立即 exit(1)（快速失败，不挂着）
- 提供 `scripts/download_models.sh`（`huggingface-cli download microsoft/TRELLIS.2-4B`）
- **镜像不含权重**，只含代码和依赖

---

## 6. 任务状态与进度定义

基于 TRELLIS2 实际三阶段重新映射：

| 状态 | 进度 | 说明 | 对应耗时占比 |
|---|---|---|---|
| submitted | 0% | 刚提交 | — |
| preprocessing | 1–5% | 图像下载/解码/归一化 | CPU，< 5s |
| gpu_queued | 5% | 等待 GPU Worker 空闲 | 排队等待 |
| gpu_ss | 6–25% | Sparse Structure（12步）| GPU，~10% 时间 |
| gpu_shape | 26–60% | Shape Geometry（20步）| GPU，~55% 时间 |
| gpu_material | 61–90% | PBR Material（12步）| GPU，~35% 时间 |
| exporting | 91–99% | o_voxel GLB 导出 | CPU，5-10s |
| uploading | 99% | MinIO 上传 | IO，2-5s |
| succeeded | 100% | 完成，artifacts 可用 | — |
| failed | — | 附带 error_message + failed_stage | — |
| cancelled | — | 主动取消 | — |

进度回传时机：
- GPU 内各阶段完成时（SS→Shape→Material，3 个钩子）
- 不在每个 step 回传（step 级别太频繁，且 flow matching 每步很快）

---

## 7. 耗时特征与设计调整

基于实际速度（A100 ~25s/任务，RTX 4090 ~60s/任务），修正之前的设计：

### 7.1 任务时长重新定标
- **不是"5-15 分钟"**，是 **30 秒到 4 分钟**（取决于 GPU 和分辨率）
- 但对于移动端用户，这依然是"长等待"，SSE 连接仍可能断开
- Webhook callback 依然是必要的设计

### 7.2 轮询 + Webhook 双保险
- `GET /v1/tasks/{id}` 轮询：每 3-5 秒一次（分辨率低时 30 秒内完成）
- Webhook callback：任务完成/失败时 POST 回 server
- SSE 保留：供前台 Web 端使用

### 7.3 VRAM 保守，批大小保持小
- 单任务 1024³ 需要约 18-22GB VRAM
- 24GB 卡：`max_batch_size = 1`（安全）或 `2`（需实测）
- 加 20% 安全裕量；VRAM 预检在 batch 开始前执行

### 7.4 批次等待窗口
- `max_queue_delay_ms = 5000`（5 秒）
- 用户等 30-60 秒，5 秒凑批毫无感知

### 7.5 Step 参数透传（仍是一等公民）
- 默认：SS=12, Shape=20, Material=12（官方默认）
- 快速模式：SS=8, Shape=12, Material=8（速度约快 40%）
- 高质量：SS=20, Shape=50, Material=20（速度约慢 2x）
- ETA 计算时需感知步数（步数影响 GPU 时间线性）

### 7.6 进度持久化频率
- 每阶段完成（SS/Shape/Material 各一次），写入 DB
- 不需要每 10 步写一次（step 级别太细，且每步很快）

### 7.7 任务超时时间
- `task_timeout_seconds = 600`（10 分钟，远超实际需要）
- 超时 → `failed(timeout)` → 自动重试 1 次
- 10 分钟内未完成说明有异常，不是正常运行

### 7.8 ETA 跨阶段计算
```
estimatedWaitSeconds =
  gpu_queue_depth × avg_gpu_time(resolution, steps)
  + remaining_gpu_time(current_stage, current_step, steps)  ← 正在运行时
  + avg_export_time
```

---

## 8. API 设计

```
POST   /v1/tasks
  Auth: Bearer <API_TOKEN>
  Body: {
    type: "image_to_3d",
    image_url: str,                         # real mode must be http(s)
    callback_url: str (optional),          # http(s), optional host allowlist
    idempotency_key: str (optional),
    options: {
      resolution: int (default 1024),        # 512 / 1024 / 1536
      ss_steps: int (default 12),
      shape_steps: int (default 20),
      material_steps: int (default 12),
      ss_guidance_scale: float (default 7.5),
      shape_guidance_scale: float (default 7.5),
      material_guidance_scale: float (default 3.0),
      decimation_target: int (default 1000000),
      texture_size: int (default 4096)
    }
  }
  Returns: { taskId, status, queuePosition, estimatedWaitSeconds, estimatedFinishAt }

GET    /v1/tasks/{id}
  Returns: {
    taskId, status, progress, currentStage,
    queuePosition, estimatedWaitSeconds, estimatedFinishAt,
    createdAt, startedAt, updatedAt, error, artifacts
  }

GET    /v1/tasks/{id}/events              # SSE
  Streams: { event, data: { stage, progress, message } }

POST   /v1/tasks/{id}/cancel

GET    /v1/tasks/{id}/artifacts
  Returns: { artifacts: [{ type: "glb", url: "<proxy-or-presigned>", expires_at }] }

GET    /v1/tasks/{id}/artifacts/{filename}
  Returns: local backend artifact bytes via API proxy

GET    /health   GET /ready   GET /metrics
```

### Webhook 回调格式
```json
POST {callback_url}
{
  "taskId": "...",
  "status": "succeeded",
  "artifacts": [{ "type": "glb", "url": "...", "expires_at": "..." }],
  "error": null
}
```

---

## 9. 存储设计

### SQLite（任务持久化）
```sql
-- tasks
id TEXT PRIMARY KEY,
status TEXT,
type TEXT DEFAULT 'image_to_3d',
input_url TEXT,
options_json TEXT,
idempotency_key TEXT UNIQUE,
callback_url TEXT,
output_artifacts_json TEXT,
error_message TEXT,
failed_stage TEXT,                    -- 在哪个阶段失败（诊断用）
retry_count INTEGER DEFAULT 0,
assigned_worker_id TEXT,
current_stage TEXT,                   -- 阶段完成时更新（非每步）
created_at TEXT, queued_at TEXT, started_at TEXT,
completed_at TEXT, updated_at TEXT

-- task_events（追加，审计用）
id INTEGER PRIMARY KEY AUTOINCREMENT,
task_id TEXT,
event TEXT,                           -- stage_complete / failed / cancelled
metadata_json TEXT,
created_at TEXT
```

### MinIO
```
artifacts/{taskId}/model.glb
artifacts/{taskId}/preview.png
```

### Redis（Phase C+ 按需引入）
- Phase A/B：纯 asyncio 内存队列，不需要 Redis
- Phase C+：若多进程/多实例需要共享状态再引入

---

## 10. 可观测性

```
gen3d_queue_depth                    # GPU Stage 等待队列深度
gen3d_gpu_task_duration_seconds      # GPU 推理耗时 histogram（label: resolution）
gen3d_stage_duration_seconds{stage}  # 各阶段（SS/Shape/Material/Export）耗时
gen3d_task_e2e_duration_seconds      # 端到端耗时 histogram
gen3d_gpu_memory_used_bytes{worker}  # 每 Worker 显存
gen3d_tasks_total{status}            # 任务计数
gen3d_batch_size                     # 实际批大小 histogram
gen3d_worker_busy_ratio{worker}      # Worker 忙碌率
```

---

## 11. 文件结构

```
gen3d/
├── serve.py                        # 入口：python -m gen3d.serve
├── config.py                       # ServingConfig (pydantic-settings)
│
├── engine/
│   ├── async_engine.py             # AsyncGen3DEngine（API 层异步包装）
│   ├── pipeline.py                 # PipelineCoordinator（阶段路由）
│   └── sequence.py                 # RequestSequence（请求状态机）
│
├── stages/
│   ├── base.py                     # BaseStage 接口
│   ├── preprocess/
│   │   └── stage.py                # CPU 图像预处理（async）
│   ├── gpu/
│   │   ├── stage.py                # GPUStage（Worker 池管理 + 调度器）
│   │   ├── scheduler.py            # FlowMatchingScheduler（批次形成）
│   │   └── worker.py               # GPUWorker 子进程（Trellis2Pipeline）
│   └── export/
│       └── stage.py                # CPU 线程池（o_voxel GLB + MinIO）
│
├── model/
│   ├── base.py                     # BaseModelProvider 接口（所有模型必须实现）
│   ├── trellis2/
│   │   └── provider.py             # Trellis2Provider（封装官方 pipeline）
│   └── hunyuan3d/
│       └── provider.py             # Hunyuan3DProvider（未来实现）
│
├── api/
│   ├── server.py                   # FastAPI app
│   └── schemas.py                  # Pydantic 请求/响应模型
│
├── storage/
│   ├── task_store.py               # SQLite 读写（aiosqlite）
│   └── artifact_store.py          # MinIO 封装（aiobotocore）
│
├── observability/
│   └── metrics.py                  # Prometheus metrics
│
├── scripts/
│   ├── download_models.sh          # huggingface-cli download TRELLIS.2-4B
│   └── bench.py                    # 压测脚本（并发阶梯）
│
├── docker/
│   ├── Dockerfile.serve            # API + Coordinator 镜像（无 GPU）
│   └── Dockerfile.worker           # Worker 镜像（CUDA + torch + trellis2）
│
├── deploy/
│   └── docker-compose.yml          # 单机多卡部署
│
├── tests/
│   ├── test_api.py
│   ├── test_pipeline.py
│   └── test_scheduler.py
│
├── requirements.txt                # 服务依赖（无 GPU）
├── requirements-worker.txt         # Worker 依赖（torch + cuda + trellis2 + o_voxel）
└── docs/
    ├── PLAN.md                     # 原始规划（保留）
    └── PLAN-v2.md                  # 本文档
```

---

## 12. 里程碑

### Phase A（1 周）：骨架 + Mock 跑通
1. 项目骨架 + docker-compose（MinIO + SQLite）
2. `RequestSequence` 状态机 + `task_store.py`
3. `GPUStage` + `FlowMatchingScheduler` + GPUWorker（mock pipeline，sleep 模拟耗时）
4. `PipelineCoordinator`：Preprocess → GPU → Export 串联
5. 基础 API（提交/查询/取消/下载）+ 内部 auth
6. 端到端冒烟（mock，验证状态流转、进度上报、Webhook 回调）

### Phase B（1 周）：接入真实 TRELLIS2
1. `model/trellis2/pipeline.py`：封装官方 `Trellis2ImageTo3DPipeline`
2. GPUWorker 换用真实 pipeline，含 SS/Shape/Material 进度 hook
3. ExportStage：`o_voxel.postprocess.to_glb()` + MinIO 上传
4. SSE 实时进度推送
5. ETA 估算（滑动窗口，跨阶段）
6. Worker Graceful Drain（SIGTERM）
7. 多 GPU 数据并行验证（2+ GPU）

### Phase C（1 周）：稳定性与可观测性
1. Prometheus 指标 + Grafana 看板
2. 压测脚本（1024³，并发 5/10/20 阶梯）
3. 故障注入（Worker OOM、MinIO 失败、超时）
4. 任务超时（10 分钟）+ 自动重试（max 1 次）
5. 验收门槛达标

### Phase D（后续）
1. **阶段解耦**：拆分 SS+Shape（GPU池A）与 Material（GPU池B），实现级间流水线并行
2. text_to_3d（t2i 独立 Stage + TRELLIS2 串联）
3. 多机扩展（Worker 远程化，zmq/gRPC）
4. 对外开放（多租户 API Key、计费）
5. Cache-DiT 风格优化（扩散 step 间激活缓存）

---

## 13. 与 server 集成

- `server` 配置 `GEN3D_BASE_URL` 和 `GEN3D_API_KEY`
- iOS 发起生成 → server 调 `POST /v1/tasks`（含 `callback_url`）
- gen3d 完成后 POST 回调 server → server 更新资产状态 → iOS 下次轮询时获得结果
- gen3d 不直接感知 iOS

---

## 14. 验收门槛（Phase C 结束）

| 指标 | 门槛 |
|---|---|
| 稳态 GPU 利用率 | ≥ 70% |
| 任务成功率（剔除非法输入）| ≥ 95% |
| ETA 误差 P90 | ≤ 30% |
| 提交后可查询状态 | ≤ 1 秒 |
| Worker 崩溃 → 任务重新入队 | ≤ 60 秒 |
| 端到端 P90 延迟（A100，1024³，无排队）| ≤ 45 秒 |
