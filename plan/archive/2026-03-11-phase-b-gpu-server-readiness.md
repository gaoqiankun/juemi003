# gen3d Phase B 第三轮：GPU 服务器部署就绪

Date / Status: 2026-03-11 / done

## Goal

在保留现有 API / Engine / Pipeline / Provider / Store 分层的前提下，把 gen3d 从“本地开发机上的 fail-fast 原型”推进到“可部署到单机单卡 GPU 服务器并进行真实验收”的状态：补齐 worker 依赖、权重下载脚本、Docker / compose 材料、real mode 自检和服务器 smoke / 验收文档。

## Key Decisions

- 不把当前 macOS 开发机上的 real mode 成功生成作为验收目标；本轮重点是部署材料、自检和文档，而不是虚报本地实机成功
- 保留 `PROVIDER_MODE=mock|real` 与 `ARTIFACT_STORE_MODE=local|minio` 两套开关，不改现有请求链路与对外语义
- 真实环境自检优先复用现有 provider/store fail-fast 逻辑，避免在 API / stage / engine 外再造一套平行配置语义
- 自动化测试继续以 mock / no-GPU 环境为主，通过单测验证自检与 fail-fast，不依赖真实 GPU 或真实 MinIO

## Changes

- `serve.py` 新增 `--check-real-env`，可在真正启动服务前单独执行 real mode 服务器自检，并以 JSON 输出成功/失败结果
- `api/server.py` 新增 `run_real_mode_preflight()`，统一复用现有 provider/store fail-fast 逻辑检查：
- `PROVIDER_MODE=real`
- artifact backend 配置与 MinIO bucket 初始化
- TRELLIS2 runtime 与模型目录
- `model/trellis2/provider.py` 新增 `inspect_runtime()` / `_inspect_runtime()`，把 real mode 对 `torch` / CUDA / `trellis2` / pipeline class / 模型加载的检查收口为可复用自检逻辑，`from_pretrained()` 也复用同一套路径
- `requirements-worker.txt` 从占位说明升级为 GPU 服务器依赖说明文件，补充 `huggingface_hub` / `accelerate` / `safetensors` 以及 torch / TRELLIS2 推荐安装命令
- 新增 `scripts/download_models.sh`，支持用 `huggingface-cli` 或 `python -m huggingface_hub` 下载 `microsoft/TRELLIS.2-4B` 到本地模型目录
- 新增 `docker/Dockerfile.worker`，提供单机单卡 GPU 服务器镜像起点：
- CUDA 12.4 base image
- 安装 worker 依赖
- 安装 CUDA 版 torch
- 安装 TRELLIS2 runtime
- 默认 real + local backend 启动参数
- 新增 `deploy/docker-compose.yml`，提供单机单卡 `gen3d` 服务和可选 `minio` / `minio-init` profile
- `README.md` 重写为 GPU 服务器验收手册，补齐：
- host 安装步骤
- Docker / compose 方案
- 权重下载
- 环境变量
- `--check-real-env` 用法
- local / minio smoke
- 真实任务服务器验收清单
- 出错后的排查顺序
- `tests/test_api.py` 新增 no-GPU 环境下的自检覆盖：
- `--check-real-env` 必须在 `PROVIDER_MODE=real` 下执行
- preflight 会同时检查 artifact backend 与 runtime probe
- 本轮本地执行 `python -m pytest tests -q`，结果为 `20 passed`

## Notes

- 当前这台 macOS 开发机仍不具备真实 TRELLIS2 推理条件，因此本轮目标明确是“部署就绪”，不是“本机成功生成”
- 当前仓库已经为 GPU 服务器准备好的材料包括：
- real mode 单独自检入口
- worker 依赖清单
- 权重下载脚本
- Dockerfile.worker
- 最小 compose
- local / minio 两套 smoke 文档
- 真实任务服务器验收清单
- 当前仍依赖的外部条件：
- Linux + NVIDIA GPU 服务器
- 兼容的 CUDA / torch 组合
- 可工作的 TRELLIS2 runtime
- 本地模型目录
- 如果要验 minio，则还需要真实对象存储
- 到服务器后的第一轮建议验收顺序：
- 先跑 `python serve.py --check-real-env`
- 再跑 `ARTIFACT_STORE_MODE=local` 的真实 smoke
- 本地 GLB 验通后再切到 `ARTIFACT_STORE_MODE=minio`
- 当前没有虚报以下未验证项：
- 真实 GPU 成功生成
- 真实 MinIO 手工 smoke
