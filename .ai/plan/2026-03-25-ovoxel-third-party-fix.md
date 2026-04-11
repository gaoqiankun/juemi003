# o-voxel third_party 依赖修复
Date: 2026-03-25
Status: done

Date / Status: 2026-03-25 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
定位 `docker/trellis2/Dockerfile` 中 o_voxel 扩展编译失败根因，并用最小改动修复。

## Key Decisions
- `model/trellis2/ext/o-voxel/third_party/eigen` 目录为空，判定为 TRELLIS.2 源码迁入时未带上 Eigen 头文件（常见于未递归初始化 submodule）。
- `o_voxel` 扩展源码唯一显式 third_party 头依赖是 `Eigen/Dense`，最小修复为在 Docker builder 安装 `libeigen3-dev`，并把 `/usr/include/eigen3` 映射到 `third_party/eigen`。
- 避免新增额外外部 git clone 步骤，保持构建链路最小增量。

## Changes
- 检查 `model/trellis2/ext/o-voxel/third_party/`：
  - `third_party/eigen` 为空目录（无任何文件）。
  - 当前仓库无 `o-voxel` 相关 `.gitmodules`；`setup.py` 里有 `include_dirs=[.../third_party/eigen]`。
- 扫描 `model/trellis2/ext/o-voxel/src/**/*.cpp|*.cu` 的 `#include`，第三方/外部头为：
  - `Eigen/Dense`
  - `torch/extension.h`
  - `cuda.h` / `cuda_runtime.h` / `cooperative_groups.h`
- 修改 `docker/trellis2/Dockerfile`：
  - builder apt 依赖新增 `libeigen3-dev`
  - 在安装 `o-voxel` 前新增：
    - `rm -rf /workspace/model/trellis2/ext/o-voxel/third_party/eigen`
    - `ln -s /usr/include/eigen3 /workspace/model/trellis2/ext/o-voxel/third_party/eigen`

## Notes
- 基线：`.venv/bin/python -m pytest tests -q`（开工前）
- 基线结果：`163 passed in 33.72s`
- 验收：
  - `hadolint` 不存在（`hadolint not found`）
  - `bash -n docker/trellis2/Dockerfile` 通过
