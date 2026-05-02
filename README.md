# Cubie

可私有部署的开源 3D 生成服务。上传一张图片，生成可下载的 GLB 3D 模型。

对标 Meshy / Tripo3D 等商业产品，定位类似 ComfyUI 在图像生成领域的地位。

## 功能

- **图片 → 3D**：上传图片，队列调度，GPU 推理，导出 GLB + 预览图
- **多模型支持**：Trellis2、HunYuan3D-2、Step1X-3D，Admin 面板动态切换
- **Web UI**：生成进度 SSE 实时推送，Three.js 3D 查看器（texture/clay/wireframe）
- **Admin 面板**：任务监控、模型管理、API Key 管理、系统设置
- **灵活部署**：本地磁盘或 S3 兼容对象存储，Docker Compose 一键启动

## 系统要求

- Linux，建议 Ubuntu 22.04+
- NVIDIA GPU，建议 24GB+ 显存（CUDA 12.4）
- NVIDIA Driver + Container Toolkit
- Docker Engine + Docker Compose Plugin

## 快速开始

```bash
# 1. 准备配置文件
cp .env.example .env
# 编辑 .env，至少设置：
#   ADMIN_TOKEN=your-secret-token
#   PROVIDER_MODE=real          # 无 GPU 时用 mock
#   MODEL_PATH=/models/trellis2

# 2. 启动
docker compose up --build

# 访问 http://127.0.0.1:18001
```

## 本地开发

```bash
# 后端
uv sync
uv run python -m cubie.serve
uv run python -m pytest tests -q       # 221 passed

# 前端
cd web
npm ci && npm run build         # 构建到 web/dist/
npm run dev -- --host 127.0.0.1 --port 5173  # 开发服务器
```

## 目录结构

```
gen3d/
├── cubie/api/               FastAPI 路由与 Schema
├── cubie/task/              任务引擎（调度 / 状态机 / SQLite）
├── cubie/model/providers/   Provider 实现（trellis2 / hunyuan3d / step1x3d）
├── cubie/stage/             任务 Stage（preprocess / gpu / export）
├── cubie/artifact/          产物存储（本地文件系统 / MinIO）
├── cubie/auth/              API Key 与鉴权
├── cubie/settings/          服务设置持久化
├── cubie/core/              配置、分页、安全、观测
├── web/        React 前端 SPA
├── docker/     Dockerfile
├── scripts/    烟测脚本、模型下载脚本
└── docs/       架构文档
```

## 相关文档

- [架构与设计决策](docs/PLAN.md)
- [开发规范（AI Coder）](AGENTS.md)
- [前端开发规范](web/AGENTS.md)

## License

Apache License 2.0，详见 [LICENSE](./LICENSE)。
