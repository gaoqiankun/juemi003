# Hunyuan3D Checkpoint Loading Fix
Date: 2026-03-26
Status: done

Date / Status: 2026-03-26 / done / Commits: N/A（未执行 git commit）
## Goal
修复 hunyuan3d shape/texture pipeline 的 `from_pretrained`，使其按原始 hy3dgen 逻辑加载 checkpoint（不依赖 diffusers `model_index.json`）。

## Key Decisions
- shape 与 texture 均改为“薄包装 + 委托上游 hy3dgen pipeline”模式，直接调用上游 `from_pretrained`，恢复非 diffusers checkpoint 的加载语义。
- 保持 provider 调用方式不变（`Hunyuan3DProvider` 继续调用本仓 `model/hunyuan3d/pipeline/*`），避免 API 层和调度层联动修改。
- 新增 HunYuan3D-2 本地源码路径注入（`sys.path` 指向 `gen3d/Hunyuan3D-2`）与运行时错误提示，缺源码时快速失败。

## Changes
- 修改 `model/hunyuan3d/pipeline/shape.py`：
  - 删除 `diffusers.DiffusionPipeline.from_pretrained` 加载路径。
  - 改为动态加载 `hy3dgen.shapegen.pipelines.Hunyuan3DDiTFlowMatchingPipeline` 并委托其 `from_pretrained`。
  - `to()` 改为兼容上游返回 `None` 的语义（不再盲目覆盖 `self._pipeline`）。
- 修改 `model/hunyuan3d/pipeline/texture.py`：
  - 删除 `diffusers.DiffusionPipeline.from_pretrained` 加载路径。
  - 改为动态加载 `hy3dgen.texgen.pipelines.Hunyuan3DPaintPipeline` 并委托其 `from_pretrained`。
  - 保留原 wrapper 的调用兼容层（mesh/image 参数尝试、输出抽取逻辑）。
- 未修改 `model/hunyuan3d/provider.py`（现有调用方式可直接复用）。
- 更新 `.ai/decisions.md`：记录 HunYuan3D checkpoint 加载语义回退为上游 hy3dgen 方式。

## Notes
- 基线：`.venv/bin/python -m pytest tests -q` -> `163 passed`。
- 代码检查：`.venv/bin/ruff check model/hunyuan3d/pipeline/shape.py model/hunyuan3d/pipeline/texture.py model/hunyuan3d/provider.py` -> `All checks passed!`
- 验收：`.venv/bin/python -m pytest tests -q` -> `163 passed in 33.60s`
