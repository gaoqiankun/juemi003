# Step1X-3D 推理代码与扩展内化
Date / Status: 2026-03-25 / done / Commits: N/A（按仓库规范本次不执行提交）

## Goal
将 Step1X-3D 推理核心 Python 代码与 C++/CUDA 扩展源码迁入仓库，移除运行时对 `/opt/Step1X-3D` 外部 clone 与 PYTHONPATH 注入依赖。

## Key Decisions
- 在 `model/step1x3d/pipeline/` 建立本地推理子包，provider 仅切换 import 来源。
- 保持 mock provider 与 BaseModelProvider 协议签名不变。
- `custom_rasterizer` 与 `differentiable_renderer` 以官方目录结构完整迁移到 `model/step1x3d/ext/`，源码不做改写。
- Dockerfile 删除 Step1X-3D clone，改为从仓库内 ext 路径编译安装，并移除 `/opt/Step1X-3D` 的 PYTHONPATH。

## Changes
- Step A（完成）：
  - 新增 `model/step1x3d/pipeline/` 子包，迁入 Step1X-3D 推理核心代码（geometry + texture），并删除 `data/`、`systems/` 等训练/数据相关目录。
  - 迁移后将原 `step1x3d_*` 路径导入改为仓库内 `gen3d.model.step1x3d.pipeline.*` 路径，不再依赖外部 repo PYTHONPATH。
  - 在迁入的 DINOv2 与 geometry pipeline 文件应用既有运行时补丁（`initialize_weights` no-op、`check_inputs` 条件修正）。
- Step B（完成）：
  - 迁入 `custom_rasterizer` 至 `model/step1x3d/ext/custom_rasterizer/`（完整目录，源码未改）。
  - 迁入 `differentiable_renderer` 至 `model/step1x3d/ext/differentiable_renderer/`（完整目录，源码未改）。
- Step C（完成）：
  - 更新 `model/step1x3d/provider.py`，real mode 改为加载仓库内 Step1X-3D pipeline。
  - 更新 `docker/trellis2/Dockerfile`（共享构建）：
    - 删除 Step1X-3D `git clone` 与针对 `/opt/Step1X-3D` 的 patch 步骤。
    - 改为 `COPY model/step1x3d/ext/*` 并从本地路径编译安装两个扩展。
    - 删除 runtime 阶段 `/opt/Step1X-3D` 的 `COPY` 与 `PYTHONPATH`。
  - 更新 `docker/trellis2/build.sh` 构建上下文到仓库根目录，确保 Dockerfile 可读取 `model/*/ext` 本地路径。
  - 更新 `ruff.toml`，排除 `model/step1x3d/ext/custom_rasterizer` 与 `model/step1x3d/ext/differentiable_renderer`（上游第三方源码）。

## Notes
- 基线：`.venv/bin/python -m pytest tests -q` -> `163 passed`
- 完工验收：
  - `.venv/bin/ruff check model/step1x3d/` -> `All checks passed!`
  - `grep -r "from step1x3d" model/` -> 无结果
  - `grep -r "import step1x3d" model/` -> 无结果
  - `.venv/bin/python -m pytest tests -q` -> `163 passed`
- 文件体积说明：迁入上游推理实现后有多处文件超过 300 行（含 >500 行），本次按“直迁优先、行为对齐”保留原结构，后续可再拆分。
