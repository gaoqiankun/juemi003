# Trellis2 推理代码与扩展内化
Date: 2026-03-25
Status: done

Date / Status: 2026-03-25 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
将 Trellis2 推理代码和 o-voxel 扩展源码内化到仓库，移除运行时对外部 `/opt/TRELLIS.2` clone 目录的依赖。

## Key Decisions
- 在 `model/trellis2/pipeline/` 放置可直接 import 的本地推理子包。
- `provider.py` 接口签名保持不变，仅替换内部 import 来源。
- `o-voxel` 以官方目录结构完整迁移到 `model/trellis2/ext/o-voxel/`，源码不做改写。
- Dockerfile 改为从本地 `o-voxel` 编译安装，不再 `git clone TRELLIS.2`。

## Changes
- Step A（完成）：
  - 新增 `model/trellis2/pipeline/` 子包，迁入 Trellis2 推理核心代码与必要依赖子模块：
    - `pipelines/`（含 `trellis2_image_to_3d.py`、samplers、rembg）
    - `models/`、`modules/`、`representations/`、`utils/`（推理时所需）
  - 清理非必要工具文件，仅保留 `utils/elastic_utils.py`（被 `models/sparse_elastic_mixin.py` 依赖）。
  - `model/trellis2/pipeline/__init__.py` 提供惰性导出入口，避免 provider import 时提前拉起重依赖。
- Step B（完成）：
  - 迁入官方 `o-voxel` 完整目录到 `model/trellis2/ext/o-voxel/`，保留 `src/`、`setup.py`、`third_party/` 等源码结构。
- Step C（完成）：
  - 更新 `model/trellis2/provider.py`，real mode runtime 改为 import 仓库内 `gen3d.model.trellis2.pipeline.pipelines`。
  - 更新 `docker/trellis2/Dockerfile`：
    - 删除 TRELLIS.2 clone 相关 ARG/RUN 与 `/opt/TRELLIS.2` 相关 COPY/PYTHONPATH。
    - 增加本地 `o-voxel` 目录 COPY，并改为 `python -m pip install model/trellis2/ext/o-voxel --no-build-isolation`。
  - 更新 `ruff.toml`，排除 `model/trellis2/ext/o-voxel`（第三方上游源码）以满足本仓 lint 规则。

## Notes
- 基线：`.venv/bin/python -m pytest tests -q` -> `163 passed`
- 文件体积说明：部分迁入文件（如 `pipelines/trellis2_image_to_3d.py`、`modules/sparse/basic.py`）超过 300 行，属于上游推理实现直迁，暂保持原结构以降低行为偏差。
- 验收：
  - `.venv/bin/ruff check model/trellis2/` -> `All checks passed!`
  - `grep -r "from trellis2\\." model/` -> 无结果
  - `grep -r "import trellis2" model/` -> 无结果
  - `.venv/bin/python -m pytest tests -q` -> `163 passed`
