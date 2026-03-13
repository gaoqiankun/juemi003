# flash-attn Docker 目录落位
Date / Status: 2026-03-12 / done / Commits: pending

## Goal

把独立试验出来的 `flash-attn` 基础镜像构建材料纳入 `gen3d` 子仓库，避免继续散落在工作区根目录，并收敛成单入口脚本。

## Key Decisions

- 目录落位在 `gen3d/docker/flashattn/`
- 保留两层镜像：
  - 工作镜像：`hey3d/flashattn-devel:latest`、`hey3d/flashattn-runtime:latest`
  - 发布镜像：`hey3d/flashattn:<flashattn>-torch<torch>-cuda<cuda>-cudnn<cudnn>-<flavor>`
- 构建/重建/自动 retag 统一收敛到一个 `build.sh`
- `runtime` 镜像继续通过 `Dockerfile.runtime` 从 `devel` 镜像复制 `/opt/conda`

## Changes

- 将原工作区根目录的 `flashattn-base/` 迁移到 `gen3d/docker/flashattn/`
- 保留以下文件：
  - `Dockerfile`
  - `Dockerfile.runtime`
  - `docker-compose.yaml`
  - `build.sh`
- `build.sh` 现在负责：
  - 检查 `hey3d/flashattn-devel:latest` / `hey3d/flashattn-runtime:latest` 是否已存在
  - 默认交互确认是否重建
  - `--force` 时直接重建
  - `devel` 重建后自动连带重建 `runtime`
  - 如果未显式设置 `PIP_INDEX_URL` / `PIP_EXTRA_INDEX_URL` / `PIP_TRUSTED_HOST` / `PIP_DEFAULT_TIMEOUT`，则尝试从宿主机 pip 配置读取并透传给 `docker compose build`
  - 如果未显式设置 `FLASH_ATTN_INSTALL_TARGET`，则在 build 前读取 base image 的 `torch/python/cuda/cxx11abi` 信息，并查询 flash-attn 官方 GitHub release 资产，优先匹配官方 wheel URL
  - 从已构建镜像读取 `flash-attn` / `torch` / CUDA / cuDNN 版本并自动 retag，且 tag 顺序以 `flash-attn` 版本为主

## Notes

- `docker compose config` 可在新目录下正常展开；新版本 CLI 会提示 `version` 字段过时，但保留该字段是为了兼容服务器上的老版 `docker-compose`
- `build.sh` 现已改为 fail-fast：若未显式指定 `FLASH_ATTN_INSTALL_TARGET` 且无法在指定 release 中匹配官方 wheel，则直接退出，不再回退安装裸 `flash-attn`
- 本轮未实际在当前机器重新构建 `flashattn` 镜像，只做了目录迁移和脚本/compose 级校验
- `Commits` 保持 `pending`
