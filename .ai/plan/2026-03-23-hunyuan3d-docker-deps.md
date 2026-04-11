# HunYuan3D-2 依赖集成到 Trellis2 Docker 基础镜像
Date: 2026-03-23
Status: done

Date / Status: 2026-03-23 / done / Commits: N/A（按 AGENTS.md，本轮不执行 commit）
## Goal
按任务要求修改 `docker/trellis2/Dockerfile`：

- builder stage 追加 HunYuan3D-2 依赖安装和 C++ 扩展编译
- runtime stage 追加 HunYuan3D-2 目录 COPY 和 PYTHONPATH

## Key Decisions

- 严格按指令在现有 trellis2 pip install 后插入新增依赖安装，避免重排原有 Trellis2 构建链路。
- builder stage 使用 `python -m pip` 统一安装方式，减少环境差异。
- runtime stage 采用 `PYTHONPATH=/opt/TRELLIS.2:/opt/Hunyuan3D-2`，保留原 Trellis2 路径并追加 hy3dgen 路径。

## Changes

- 更新 `docker/trellis2/Dockerfile`：
  - 新增 pip 依赖：`pybind11`、`diffusers`、`einops`、`accelerate`、`omegaconf`、`pymeshlab`、`pygltflib`、`xatlas`
  - 新增 HunYuan3D-2 clone + editable install：
    - `git clone https://github.com/Tencent/Hunyuan3D-2 /opt/Hunyuan3D-2`
    - `cd /opt/Hunyuan3D-2 && python -m pip install -e .`
  - 新增两个扩展编译安装：
    - `hy3dgen/texgen/custom_rasterizer`
    - `hy3dgen/texgen/differentiable_renderer`
  - runtime stage 新增：
    - `COPY --from=builder /opt/Hunyuan3D-2 /opt/Hunyuan3D-2`
    - `ENV PYTHONPATH=/opt/TRELLIS.2:/opt/Hunyuan3D-2`

## Notes

- 按最新用户要求「不要在本地编译 docker」，本轮未执行本地 `docker build` 与容器内 import 验证。
- 镜像大小：未测（本地构建已跳过）；待 CI 或远端构建完成后补录实际镜像大小。
