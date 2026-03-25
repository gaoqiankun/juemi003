# gen3d TRELLIS.2 Docker 安装修复
Date / Status: 2026-03-11 / done

## Goal

修复 `docker/Dockerfile.worker` 中错误的 TRELLIS 安装方式，避免再使用仓库根目录 `pip install git+https://github.com/microsoft/TRELLIS.git` 导致镜像构建失败。

## Key Decisions

- 官方当前用于图像到 3D 生成的是 `microsoft/TRELLIS.2`，而不是旧的 `microsoft/TRELLIS`
- `TRELLIS.2` 仓库根目录不是可直接 `pip install` 的 Python 项目，因此 Docker 构建里改为 `git clone --recursive` + `PYTHONPATH` 方式接入源码
- 参照官方 `setup.sh` 的依赖列表，在镜像中显式安装 `trellis2` / `o_voxel` 运行所需依赖和扩展，避免继续依赖失效的 pip git root 安装路径
- `torch` 改为固定到 TRELLIS.2 README 默认组合 `2.6.0 / 0.21.0 / 2.6.0 + cu124`，避免 Docker build 里再由 pip 自行解析到不稳定组合
- 在原生扩展编译前增加 `torch` / `TORCH_CUDA_ARCH_LIST` 预检，把 `_get_cuda_arch_flags` 问题提前到更清晰的失败点
- 去掉 `Dockerfile.worker` 里的 `INTERNAL_API_KEY` 镜像级默认值，避免继续触发敏感信息告警

## Changes

- 更新 `docker/Dockerfile.worker`：
  - 改用 `microsoft/TRELLIS.2.git`
  - `git clone --recursive` 到 `/opt/TRELLIS.2`
  - 设置 `PYTHONPATH=/opt/TRELLIS.2`，避免 Docker 的未定义变量 warning
  - `torch` 固定为 `2.6.0 / 0.21.0 / 2.6.0 + cu124`
  - 在构建阶段打印并校验 `torch.__version__`、`torch.version.cuda`、`TORCH_CUDA_ARCH_LIST`、`_get_cuda_arch_flags()`，避免继续把错误拖到 `o-voxel` 编译后半段才暴露
  - 按官方依赖补齐 `flash-attn`、`nvdiffrast`、`nvdiffrec`、`CuMesh`、`FlexGEMM`、`o-voxel` 等安装逻辑
  - 将原本聚合在一个大 `RUN` 里的原生扩展安装拆成独立步骤，方便服务器上定位到底是哪个依赖编译失败
  - `flash-attn` / `o-voxel` 改为显式继承 `TORCH_CUDA_ARCH_LIST`、`FORCE_CUDA`、`CUDA_HOME` 再安装，减少 PEP517 子构建对环境推断的依赖
  - 为 `docker build` 阶段显式引入 `TORCH_CUDA_ARCH_LIST` / `FORCE_CUDA` / `CUDA_HOME`，解决无 GPU build 环境下 `o_voxel` / `cumesh` / `flex_gemm` 无法自动推断 CUDA 架构导致的 `_get_cuda_arch_flags` 异常
- 更新 `deploy/docker-compose.yml` 的 build args，加入固定 `torch` 版本参数，并保留 `TRELLIS2_REPO_URL` / `TRELLIS2_REF`
- 更新 `README.md` 和 `requirements-worker.txt`，修正文档中的固定 `torch` 版本、GPU 架构和 Docker 重建说明

## Notes

- 当前修复针对的是 Docker 构建阶段的安装路径错误；是否还存在服务器 CUDA / 编译工具链相关问题，需要在目标 GPU 服务器上继续验证
- 本地 macOS 开发机未执行 Docker GPU 构建验证；现有自动化测试只覆盖服务逻辑，不覆盖 worker 镜像构建
