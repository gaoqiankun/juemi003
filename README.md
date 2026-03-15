# Hey3D gen3d

`gen3d` 是 Hey3D 的 3D 生成推理服务。当前仓库的重点不是在这台 macOS 开发机上跑通真实 TRELLIS2，而是把服务推进到“拿到一台单机单卡 Linux GPU 服务器后，可以直接按仓库材料完成真实验收”的状态。

## 本轮已准备好的内容

- `PROVIDER_MODE=mock|real`
- `ARTIFACT_STORE_MODE=local|minio`
- 稳定的任务 / artifact / webhook 对外语义
- `exporting -> uploading -> succeeded` 真正进入状态流
- real mode fail-fast
- `python serve.py --check-real-env` 服务器自检入口
- `requirements-worker.txt`
- `scripts/download_models.sh`
- `docker/Dockerfile`
- `docker-compose.yml`
- `deploy.sh`
- structlog JSON 结构化日志（`task_id` 贯穿处理链）
- Prometheus `/metrics` 最小生产指标
- 启动恢复中间态任务 + 超时任务 fail-fast
- webhook 指数退避重试（1s / 2s / 4s）
- 单机多卡 mock/real worker 抽象（每卡一个 slot）
- 队列有界拒绝（`QUEUE_MAX_SIZE` 满时返回 503 `queue_full`）
- mock 模式自动化测试

## 当前未宣称完成的内容

- 当前机器不是 CUDA Linux 服务器，因此没有完成真实 TRELLIS2 成功生成验收
- 当前仓库不能宣称“real mode 已本机成功生成”
- 当前也没有在真实 MinIO 上做手工 smoke，只做了 fake client / isolated test

## 状态流与外部语义

状态流：

`submitted -> preprocessing -> gpu_queued -> gpu_ss -> gpu_shape -> gpu_material -> exporting -> uploading -> succeeded`

失败会带：

```json
{
  "message": "...",
  "failed_stage": "preprocessing|gpu_ss|gpu_shape|gpu_material|exporting|uploading"
}
```

任务详情、`GET /v1/tasks/{id}/artifacts`、终态 webhook 中的 artifact 统一为：

```json
{
  "type": "glb",
  "url": "/v1/tasks/<task-id>/artifacts/model.glb 或 presigned-url",
  "created_at": "2026-03-11T08:00:00+00:00",
  "size_bytes": 123456,
  "backend": "local 或 minio",
  "content_type": "model/gltf-binary",
 "expires_at": null
}
```

如果配置了 `callback_url`，webhook 投递失败会按 `WEBHOOK_MAX_RETRIES` 做指数退避重试；每次重试和最终成功/失败都会写入 `task_events`。服务启动时也会扫描未终态任务，对 `submitted/preprocessing` 重入队，对 `gpu_queued` 及之后阶段直接失败，并对超过 `TASK_TIMEOUT_SECONDS` 的任务做超时失败收口。

`GPU_DEVICE_IDS` 控制启用几张卡；mock 模式会起对应数量的 async worker，real 模式会按卡数起独立子进程 worker。`QUEUE_MAX_SIZE` 控制等待队列上限，超出时 `POST /v1/tasks` 返回 `503`，错误码为 `queue_full`。

## GPU 服务器前置条件

真正做 real mode 验收前，服务器至少需要：

- Linux
- NVIDIA 驱动 + CUDA 兼容运行时
- 至少 1 张可见 CUDA GPU
- 建议 24GB+ VRAM
- 可安装 CUDA 版 `torch`
- 可安装 TRELLIS2 runtime
- 能访问 Hugging Face 权重，或提前准备好内网镜像
- 如果要验 `minio` backend，还需要一套可访问的 S3 兼容对象存储

当前仓库里已有的 fail-fast 覆盖：

- 缺 `torch`
- 缺 `trellis2`
- 没有可见 CUDA GPU
- `MODEL_PATH` 不存在
- `ARTIFACT_STORE_MODE=minio` 时对象存储关键配置缺失
- `ARTIFACT_STORE_MODE=minio` 时 bucket 校验失败

## 安装方式 A：直接在 GPU 服务器上安装

### 1. 准备 Python 环境

推荐 Python 3.10+。仓库本地开发固定在 3.12.7，但服务代码本身不依赖 3.12 特性专属运行时。

```bash
cd /path/to/gen3d
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### 2. 安装 gen3d 基础依赖

```bash
python -m pip install -r requirements-worker.txt
```

### 3. 安装 CUDA 版 torch

示例按 TRELLIS.2 官方默认组合 `torch 2.6.0 + CUDA 12.4`：

```bash
python -m pip install \
  torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124
```

如果你的服务器不是 CUDA 12.4，请替换成与驱动 / CUDA runtime 匹配的 PyTorch wheel 源。

### 4. 安装 TRELLIS2 runtime

官方当前可用的是 `microsoft/TRELLIS.2`，它不是仓库根目录可直接 `pip install git+...` 的布局。按官方文档，先克隆仓库，再在已有 Python 环境里安装依赖：

```bash
git clone -b main --recursive https://github.com/microsoft/TRELLIS.2.git /opt/TRELLIS.2
export PYTHONPATH=/opt/TRELLIS.2:$PYTHONPATH
cd /opt/TRELLIS.2
. ./setup.sh --basic --flash-attn --nvdiffrast --nvdiffrec --cumesh --o-voxel --flexgemm
```

如果你们生产环境使用内部镜像或固定 commit，请替换成内部仓库地址和固定 ref。

### 5. 下载模型权重

默认下载官方 `microsoft/TRELLIS.2-4B`：

```bash
MODEL_DIR=/models/trellis2 bash scripts/download_models.sh
```

常用可选参数：

```bash
MODEL_REPO_ID=microsoft/TRELLIS.2-4B
MODEL_DIR=/models/trellis2
MODEL_REVISION=main
HF_TOKEN=...
```

### 6. 配环境变量

#### local backend

```bash
export API_TOKEN=dev-api-token
export PROVIDER_MODE=real
export MODEL_PROVIDER=trellis2
export MODEL_PATH=/models/trellis2
export ARTIFACT_STORE_MODE=local
export DATABASE_PATH=/srv/gen3d/data/gen3d.sqlite3
export ARTIFACTS_DIR=/srv/gen3d/data/artifacts
export GPU_DEVICE_IDS=0
export QUEUE_MAX_SIZE=20
export ALLOWED_CALLBACK_DOMAINS=
export RATE_LIMIT_CONCURRENT=5
export RATE_LIMIT_PER_HOUR=100
export WEBHOOK_MAX_RETRIES=3
export TASK_TIMEOUT_SECONDS=3600
```

#### minio backend

```bash
export API_TOKEN=dev-api-token
export PROVIDER_MODE=real
export MODEL_PROVIDER=trellis2
export MODEL_PATH=/models/trellis2
export ARTIFACT_STORE_MODE=minio
export DATABASE_PATH=/srv/gen3d/data/gen3d.sqlite3
export ARTIFACTS_DIR=/srv/gen3d/data/artifacts
export GPU_DEVICE_IDS=0,1
export QUEUE_MAX_SIZE=20
export OBJECT_STORE_ENDPOINT=http://minio.internal:9000
export OBJECT_STORE_EXTERNAL_ENDPOINT=https://minio.example.com
export OBJECT_STORE_BUCKET=gen3d-artifacts
export OBJECT_STORE_ACCESS_KEY=minioadmin
export OBJECT_STORE_SECRET_KEY=minioadmin
export OBJECT_STORE_REGION=us-east-1
export OBJECT_STORE_PREFIX=artifacts
export OBJECT_STORE_PRESIGN_TTL_SECONDS=3600
export ALLOWED_CALLBACK_DOMAINS=callback.example.com
export RATE_LIMIT_CONCURRENT=5
export RATE_LIMIT_PER_HOUR=100
export WEBHOOK_MAX_RETRIES=3
export TASK_TIMEOUT_SECONDS=3600
```

### 7. 先跑自检

```bash
python serve.py --check-real-env
```

成功时会输出 JSON，例如：

```json
{
  "ok": true,
  "provider_mode": "real",
  "provider": {
    "provider": "trellis2",
    "model_path": "/models/trellis2",
    "torch_version": "2.x",
    "cuda_available": true,
    "cuda_device_count": 1,
    "pipeline_class": "trellis2.pipelines.Trellis2ImageTo3DPipeline",
    "pipeline_loaded": true
  },
  "artifact_store": {
    "mode": "local",
    "artifacts_dir": "/srv/gen3d/data/artifacts"
  }
}
```

失败时会直接退出非 0，并输出明确错误；例如当前开发机上：

```json
{
  "ok": false,
  "provider_mode": "real",
  "artifact_store_mode": "local",
  "error": "TRELLIS2 model path does not exist: /tmp/gen3d-missing-model"
}
```

### 8. 启动服务

```bash
python serve.py
```

或：

```bash
python -m gen3d.serve
```

## 安装方式 B：Docker / Compose

仓库内已提供：

- `docker/Dockerfile`
- `docker/trellis2/Dockerfile`
- `docker-compose.yml`
- `deploy.sh`
- `scripts/build-trellis2.sh`

它们的定位是“GPU 服务器第一轮验证材料”，不是已经在当前机器实测通过的生产镜像。
当前 `gen3d` 部署镜像已经改成基于预先构建好的 `flash-attn` 基础镜像：

- `hey3d/flashattn-devel:latest`
- `hey3d/flashattn-runtime:latest`
- `hey3d/trellis2:latest`

因此，先决条件是你已经在目标服务器上把这三层基础镜像 build 好或 load 进本地 Docker。
为避免容器把宿主机挂载目录写成 `root:root`，部署 `.env` 建议显式保留：

```dotenv
HOST_UID=<部署用户 uid>
HOST_GID=<部署用户 gid>
```

`docker-compose.yml` 会用这两个值让 `hey3d-gen3d` 进程以同一宿主机 uid/gid 运行。
同时 compose 会把 `HOME`、`HF_HOME`、`XDG_CACHE_HOME`、`TRITON_CACHE_DIR` 固定到 `/data` 下，避免非 root 运行时把缓存写到 `/.triton` 这类不可写路径。

### Docker build

先构建 `TRELLIS.2` 基础镜像：

```bash
./scripts/build-trellis2.sh --image hey3d/trellis2:latest
```

可选环境变量 build args：

```bash
export FLASHATTN_DEVEL_IMAGE=hey3d/flashattn-devel:latest
export FLASHATTN_RUNTIME_IMAGE=hey3d/flashattn-runtime:latest
export TRELLIS2_REPO_URL=https://github.com/microsoft/TRELLIS.2.git
export TRELLIS2_REF=main
export TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"
```

再构建应用镜像：

```bash
docker build -f docker/Dockerfile -t hey3d-gen3d:local .
```

可选 build args：

```bash
--build-arg TRELLIS2_IMAGE=hey3d/trellis2:latest
```

如果你们有内部 `flash-attn` 基础镜像仓库或 TRELLIS.2 私有镜像，在这里替换。
如果 `TRELLIS.2` 基础镜像在 `o_voxel` / `cumesh` / `flex_gemm` 编译阶段报
`torch.utils.cpp_extension._get_cuda_arch_flags` 相关错误，说明 `docker build`
阶段无法自动探测 GPU 架构。这时必须显式传 `TORCH_CUDA_ARCH_LIST`。

常见示例：

- A100: `8.0`
- RTX A6000 / RTX 3090: `8.6`
- RTX 4090 / L40S: `8.9`
- H100: `9.0`

如果不确定，可以先传较宽的组合：

```bash
export TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"
./scripts/build-trellis2.sh --image hey3d/trellis2:latest
```

更窄的架构列表会明显减少编译时间。
如果你修改过 `FLASHATTN_*`、`TRELLIS2_*` 或 `TORCH_CUDA_ARCH_LIST` 这类 build args，重试 `./scripts/build-trellis2.sh` 时建议带 `docker builder prune` 或手动加 `docker build --no-cache`，避免继续复用之前失败的扩展编译层。

### Compose 启动 local backend

```bash
export API_TOKEN=dev-api-token
export PROVIDER_MODE=real
export ARTIFACT_STORE_MODE=local
export GEN3D_MODEL_DIR=/absolute/path/to/models/trellis2
export TRELLIS2_IMAGE=hey3d/trellis2:latest

docker compose up --build hey3d-gen3d
```

### Compose 启动 minio backend

```bash
export API_TOKEN=dev-api-token
export PROVIDER_MODE=real
export ARTIFACT_STORE_MODE=minio
export GEN3D_MODEL_DIR=/absolute/path/to/models/trellis2
export TRELLIS2_IMAGE=hey3d/trellis2:latest
export OBJECT_STORE_ENDPOINT=http://minio:9000
export OBJECT_STORE_EXTERNAL_ENDPOINT=http://127.0.0.1:9000
export OBJECT_STORE_BUCKET=gen3d-artifacts
export OBJECT_STORE_ACCESS_KEY=minioadmin
export OBJECT_STORE_SECRET_KEY=minioadmin

docker compose --profile minio up --build minio minio-init hey3d-gen3d
```

## 服务器第一轮 smoke 流程

### Smoke 输入建议

real mode 只接受 `http(s)` 图片 URL。首轮验收建议先准备一张稳定可访问的 `http(s)` 图片，避免把鉴权和下载问题混在一起。建议：

- 单主体
- 背景尽量干净
- 正方形或接近正方形
- PNG / JPG
- 第一轮先用 `resolution=512` 或 `1024`

如果你只有服务器本地图片，请先通过 Nginx / 对象存储 / 临时静态服务把它暴露成 `http(s)` 地址。

### 提交任务

```bash
curl -X POST http://127.0.0.1:18001/v1/tasks \
  -H 'Authorization: Bearer dev-api-token' \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "image_to_3d",
    "image_url": "https://example.com/input.png",
    "options": {
      "resolution": 512
    }
  }'
```

### 观察状态

```bash
curl -N http://127.0.0.1:18001/v1/tasks/<task-id>/events \
  -H 'Authorization: Bearer dev-api-token'
```

第一轮验收时至少应看到：

- `preprocessing`
- `gpu_queued`
- `gpu_ss`
- `gpu_shape`
- `gpu_material`
- `exporting`
- `uploading`
- `succeeded`

### 查看任务详情

```bash
curl http://127.0.0.1:18001/v1/tasks/<task-id> \
  -H 'Authorization: Bearer dev-api-token'
```

### 查看 artifact

```bash
curl http://127.0.0.1:18001/v1/tasks/<task-id>/artifacts \
  -H 'Authorization: Bearer dev-api-token'
```

## local backend smoke

验收要点：

- `backend` 为 `local`
- `url` 为 `/v1/tasks/<task-id>/artifacts/model.glb`
- `expires_at` 为 `null`
- `GET /v1/tasks/<task-id>/artifacts/model.glb` 可直接下载 GLB
- 服务器本地应能看到：

`$ARTIFACTS_DIR/<task-id>/model.glb`

如果你把 `ARTIFACTS_DIR=/srv/gen3d/data/artifacts`，那么实际文件就是：

`/srv/gen3d/data/artifacts/<task-id>/model.glb`

## minio backend smoke

验收要点：

- `backend` 为 `minio`
- `url` 为 presigned URL
- `expires_at` 不为空
- 对象 key 默认应在：

`artifacts/<task-id>/model.glb`

如果启用了 webhook，终态 webhook 里的 `artifacts[0]` 也应与 `/v1/tasks/{id}` 返回保持同一结构。

## 真实任务服务器验收清单

到 GPU 服务器后，第一轮建议按下面顺序验：

1. 跑 `python serve.py --check-real-env`
2. 先用 `ARTIFACT_STORE_MODE=local` 启动服务
3. 提交 `http(s)` smoke 图，确认 real mode 输入校验通过
4. 观察事件流是否完整经过 `gpu_ss -> gpu_shape -> gpu_material -> exporting -> uploading -> succeeded`
5. 用 `GET /v1/tasks/{id}` 确认：
   - `status=succeeded`
   - `artifacts[0].backend=local`
   - `artifacts[0].url` 为 `/v1/tasks/{id}/artifacts/model.glb`
6. 在服务器磁盘确认 `model.glb` 实际存在
7. 如果配置了 webhook，确认 webhook 收到：
   - `taskId`
   - `status`
   - `artifacts`
   - `error`
8. local backend 验过后，再切 `ARTIFACT_STORE_MODE=minio`
9. 重做一次 smoke，确认：
   - `artifacts[0].backend=minio`
   - `url` 可访问
   - `expires_at` 有值
   - bucket 中存在对象

## 出错时先查什么

建议按这个顺序排：

1. 自检失败
   - `python serve.py --check-real-env`
   - 先解决 `torch` / `cuda` / `trellis2` / `MODEL_PATH` / MinIO bucket 报错
2. 启动即失败
   - 环境变量是否与当前 backend 匹配
   - `MODEL_PATH` 是否挂载到了容器 / 主机真实路径
   - `OBJECT_STORE_*` 是否完整
3. 任务卡在 `preprocessing`
   - 输入图片路径是否可读
   - 图片是否损坏
4. 任务卡在 GPU 阶段或 GPU 失败
   - `torch.cuda.is_available()`
   - 显存是否足够
   - TRELLIS2 runtime 是否与服务器 CUDA / torch 匹配
5. 任务卡在 `exporting`
   - TRELLIS2 输出对象是否暴露 `o_voxel.postprocess.to_glb()`
   - 本地磁盘空间 / 写权限
6. 任务卡在 `uploading`
   - local: `ARTIFACTS_DIR` 写权限
   - minio: bucket、endpoint、凭证、external endpoint、presign

## 自动化测试

当前自动化测试仍以 mock / no-GPU 环境为准：

```bash
python -m pytest tests -q
```

本轮完成后结果为：

- `23 passed`

这些测试覆盖：

- mock 模式完整状态流
- artifact 结构稳定性
- `uploading` 阶段真实进入状态流
- local / minio backend 失败诊断
- real mode 无效配置 / 自检 fail-fast
- `/metrics` 指标可见性与成功任务计数

## 当前还依赖哪些外部条件

这部分不在当前 macOS 开发机内完成，必须到 GPU 服务器上才可验证：

- 可见 CUDA GPU
- 兼容的 CUDA / torch 组合
- 可工作的 TRELLIS2 runtime
- 真实模型目录
- 可读的真实输入图片
- 如果要验 minio，则还需要真实对象存储及 bucket

## 代码与材料入口

- `serve.py`: 服务启动与 `--check-real-env`
- `api/server.py`: app 装配、artifact backend 校验、real preflight
- `observability/logging.py`: structlog JSON 日志配置
- `observability/metrics.py`: Prometheus 指标注册与 exposition
- `model/trellis2/provider.py`: TRELLIS2 runtime 检查与 real provider
- `requirements-worker.txt`: GPU 服务器依赖说明
- `scripts/download_models.sh`: 模型下载脚本
- `docker/Dockerfile`: GPU 服务器部署镜像起点
- `docker-compose.yml`: 单机单卡 + 可选 MinIO 的最小 compose
- `deploy.sh`: 类似 `server/` 的打包部署脚本
- `tests/test_api.py`: self-check / fail-fast / API 语义回归
- `tests/test_pipeline.py`: pipeline / artifact backend 回归

## 参考

- `docs/PLAN.md`
- `plan/2026-03-10-phase-a-architecture.md`
- `plan/2026-03-11-phase-b-real-minimum.md`
- `plan/2026-03-11-phase-b-artifact-backends.md`
- `plan/2026-03-11-phase-b-gpu-server-readiness.md`
