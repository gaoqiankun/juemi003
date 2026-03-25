# o_voxel Eigen include 路径清理
Date / Status: 2026-03-25 / done / Commits: N/A（按仓库规范本次不执行提交）

## Goal
移除 Dockerfile 中的 eigen 软链接 workaround，改为 setup.py 优先解析系统 Eigen include 路径。

## Key Decisions
- `setup.py` 将 Eigen include 路径解析改为“系统优先”：`pkg-config --cflags eigen3` → `/usr/include/eigen3` → `third_party/eigen`。
- Dockerfile 保留 `libeigen3-dev`，删除 `third_party/eigen` 软链接 workaround。

## Changes
- 修改 `model/trellis2/ext/o-voxel/setup.py`：
  - 新增 `subprocess` 导入。
  - 新增 `_resolve_eigen_include_dirs()`，优先读取 `pkg-config --cflags eigen3` 的 `-I` 路径。
  - 当 pkg-config 不可用或无有效路径时，回退到 `/usr/include/eigen3`，再回退到 `third_party/eigen`。
  - `CUDAExtension(..., include_dirs=...)` 改为使用 `EIGEN_INCLUDE_DIRS`。
- 修改 `docker/trellis2/Dockerfile`：
  - 删除 `mkdir/rm/ln -s /usr/include/eigen3 -> third_party/eigen` 的 `RUN` 步骤。
  - 保留 builder 阶段 `libeigen3-dev` 安装。

## Notes
- 基线：`.venv/bin/python -m pytest tests -q` -> `163 passed in 33.22s`
- 验收：
  - `bash -n docker/trellis2/Dockerfile` 通过
  - `python -m py_compile model/trellis2/ext/o-voxel/setup.py` 通过
