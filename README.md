# Cubify 3D

Cubify 3D 是一个可本地部署的开源 3D 生成服务，提供任务队列、Web UI、artifact 管理与 Docker 部署能力。

## 功能亮点

- 支持 `mock` / `real` 两种 provider 模式，便于本地联调和 GPU 部署
- 提供 React Web UI，可直接提交任务、查看进度、浏览结果
- 内置任务状态流、SSE 事件、artifact 下载与 webhook 回调
- 支持本地磁盘和 S3 兼容对象存储两种 artifact backend
- 提供 Docker Compose、部署脚本和最小 Prometheus 指标

## 系统要求

- Linux 主机，建议 Ubuntu 22.04+ 或同级发行版
- NVIDIA GPU，建议 24GB 及以上显存
- NVIDIA Driver + CUDA 12.4 兼容运行时
- Docker Engine + Docker Compose Plugin
- NVIDIA Container Toolkit
- Python 3.10+（本地源码运行或测试时）

## 快速开始

1. 准备模型目录与环境文件：

```bash
cp .env.example .env
mkdir -p ./models/trellis2 ./data
```

2. 编辑 `.env`，至少确认这些配置：

```bash
ADMIN_TOKEN=change-me
PROVIDER_MODE=real
MODEL_PATH=/models/trellis2
CUBIFY_MODEL_DIR=/absolute/path/to/models/trellis2
```

提示：如果只是快速 smoke test，可以先把 `PROVIDER_MODE=mock`。

3. 启动服务并打开 Web UI：

```bash
docker compose up --build
```

默认访问地址是 `http://127.0.0.1:18001/`。

## 截图

TODO: add screenshots

## 开发说明

- 本地目录名暂时仍为 `gen3d/`，以避免影响现有模块路径和脚本
- API 路径保持为 `/v1/...`
- 默认 Compose 环境变量前缀已统一为 `CUBIFY_*`

## License

本项目采用 Apache License 2.0，详见 [LICENSE](./LICENSE)。
