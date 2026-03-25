# gen3d 部署镜像切到 flash-attn 基础镜像
Date / Status: 2026-03-13 / done

## Goal

把 `gen3d` 的 GPU 部署镜像改成基于已经单独验证可构建的 `hey3d/flashattn` 基础镜像，避免在部署镜像 Dockerfile 里重复安装 `torch` 和 `flash-attn`，同时让部署命名回到单服务语义，不再把当前单体部署镜像叫成 `worker`。

## Key Decisions

- 部署镜像主 Dockerfile 收口为 `docker/Dockerfile`
- compose 主服务命名为 `hey3d-gen3d`
- 部署镜像默认命名为 `hey3d-gen3d:local`
- 对齐 `server` 子仓库的部署入口风格：根目录 `docker-compose.yml` + `deploy.sh`
- `docker/Dockerfile` 继续使用两阶段：
  - builder 基于 `hey3d/flashattn-devel:latest`
  - final 基于 `hey3d/flashattn-runtime:latest`
- 部署镜像继续在 builder 阶段编译 `o-voxel`、`nvdiffrast`、`nvdiffrec`、`CuMesh`、`FlexGEMM`
- final 镜像通过复制 `/opt/conda` 和 `/opt/TRELLIS.2` 进入 runtime，不再重复安装 `torch` / `flash-attn`
- `deploy/docker-compose.yml` 对齐 `server` 子仓库当前的单服务部署命名风格，并保持对老版 `docker-compose` 的 GPU 兼容

## Changes

- 新增 `docker/Dockerfile`
  - 删除镜像内重复安装 `torch` / `torchvision` / `torchaudio` / `flash-attn`
  - 引入 `FLASHATTN_DEVEL_IMAGE` / `FLASHATTN_RUNTIME_IMAGE` 两个 build arg
  - 将部署镜像构建改为 builder/final 两阶段
  - builder 阶段继续安装 TRELLIS.2 runtime 及其原生扩展
  - final 阶段复制 builder 的 `/opt/conda` 与 `/opt/TRELLIS.2`
  - final 阶段补齐 `build-essential` 和 `CC` / `CXX`，避免 Triton/FlexGEMM 首次运行时编译 helper 失败
- 删除 `docker/Dockerfile.gen3d`
- 新增根目录 `docker-compose.yml`
  - 主服务命名改为 `hey3d-gen3d`
  - 默认部署镜像名改为 `hey3d-gen3d:local`
  - 默认引用 `docker/Dockerfile`
  - 保持 `version: "2.4"` + `runtime: nvidia`
- 新增根目录 `deploy.sh`
  - 对齐 `server/deploy.sh` 的打包/导出/上传流程
  - 生成 `.env`、`image.tar.gz`、校验文件和快速部署说明
  - 远程部署默认使用 `/opt/hey3d/gen3d`
- 删除 `deploy/docker-compose.yml`
- 更新 `README.md`
  - 明确 `gen3d` Docker 构建依赖已先构建好的 `hey3d/flashattn-*` 基础镜像
  - 更新 Docker build / compose / deploy 示例、镜像名与服务名

## Notes

- 本轮只完成 `gen3d` 部署镜像与 `flashattn` 基础镜像的对接，不涉及再次调整 `flashattn` 基础镜像自身逻辑
- 当前 macOS 开发机未实际执行 GPU 部署镜像构建；本轮只做 Dockerfile / compose / 文档级收口
