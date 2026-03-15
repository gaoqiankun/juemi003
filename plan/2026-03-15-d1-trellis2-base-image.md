# D1 · trellis2 基础镜像分层
Date: 2026-03-15
Status: done
Commits: n/a（按要求未执行 git 操作）

## Goal
把 TRELLIS.2 CUDA 扩展编译步骤从应用镜像中剥离，形成独立的 `hey3d/trellis2` 基础镜像，使日常应用镜像 build 从 20 分钟降至 < 1 分钟。

## Key Decisions
- 新镜像命名：`hey3d/trellis2:TAG`（TAG 格式同 flashattn，如 `20260315`）
- 新增 `docker/trellis2/Dockerfile`：独立目录 + 独立 build 上下文，与 flashattn 同等地位；以 flashattn-devel/runtime 为基础，只做 TRELLIS.2 clone + 所有 CUDA 扩展编译安装，不含应用代码
- 现有 `docker/Dockerfile` 改为以 `hey3d/trellis2` 为基础，只复制应用代码和 requirements
- 新增 `scripts/build-trellis2.sh`：独立构建并可选 push `hey3d/trellis2` 镜像（手动触发，仅 TRELLIS.2 依赖变更时运行），风格与 deploy.sh 一致
- `docker-compose.yml` build.args 新增 `TRELLIS2_IMAGE`（默认 `hey3d/trellis2:latest`）
- `deploy.sh` 不需要变更

## Changes
| 文件 | 变更说明 |
|------|---------|
| `docker/trellis2/Dockerfile` | 新建独立目录，从 flashattn 镜像编译安装全部 TRELLIS.2 CUDA 扩展 |
| `docker/Dockerfile` | 改为以 `TRELLIS2_IMAGE` 为 FROM，只安装 `requirements-worker.txt` 并复制应用代码 |
| `docker-compose.yml` | build.args 收口为 `TRELLIS2_IMAGE` 参数（默认 `hey3d/trellis2:latest`） |
| `scripts/build-trellis2.sh` | 新建，封装 `docker build docker/trellis2` + 可选 push |
| `README.md` | 更新基础镜像构建顺序、build args 和 compose 使用方式 |

## Notes
- docker/trellis2/Dockerfile 构建慢（20 min+），只在 TRELLIS.2 版本或依赖变更时重建
- 应用镜像 build 后应 < 2 分钟
- scripts/build-trellis2.sh 要支持 --image、--push、--platform 参数，与 deploy.sh 风格一致
- 主镜像保留 `requirements-worker.txt` 安装，避免把应用依赖硬编码进 `docker/trellis2/` 独立上下文
- 本轮未实际运行 `docker build`，只做脚本/文档/静态校验
