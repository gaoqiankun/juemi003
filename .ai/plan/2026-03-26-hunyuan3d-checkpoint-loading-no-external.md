# Hunyuan3D Checkpoint Loading No-External Fix
Date: 2026-03-26
Status: done

Date / Status: 2026-03-26 / done / Commits: N/A（未执行 git commit）
## Goal
在不依赖 `Hunyuan3D-2/` 目录的前提下，修复 hunyuan3d shape / texture pipeline 的 checkpoint 加载逻辑，恢复不依赖 `model_index.json` 的加载方式。

## Key Decisions
- 参考 `Hunyuan3D-2/hy3dgen/*/pipelines.py` 的加载流程，但在 `model/hunyuan3d/pipeline/` 内自实现，不引入 `hy3dgen` import。
- shape pipeline 改为按 `config.yaml + model(.variant).{safetensors|ckpt}` 解析并加载权重，而非 `DiffusionPipeline.from_pretrained`。
- texture pipeline 改为按 delight/multiview 子目录解析本地/HF checkpoint 目录并实例化本仓实现，不依赖 `model_index.json`。

## Changes
- 修改 `model/hunyuan3d/pipeline/shape.py`：
  - 新增 checkpoint 资产解析：`config.yaml` + `model(.variant).{safetensors|ckpt}` 候选回退。
  - 加载入口改为 `DiffusionPipeline.from_single_file(...)`（传入 config/original_config），规避 `model_index.json` 依赖。
  - 保留 provider 对外调用接口和推理入参兼容处理。
- 修改 `model/hunyuan3d/pipeline/texture.py`：
  - 保留原始的 delight + paint 子目录资产解析方式（本地缓存 / Hugging Face）。
  - 首选 `from_pretrained`，失败后自动回退到 checkpoint 单文件加载（`from_single_file`）路径，避免 `model_index.json` 硬依赖。
  - 增加 checkpoint 文件候选解析（支持 safetensors/ckpt + variant 回退）。
- `model/hunyuan3d/provider.py`：无需改动，现有调用方式可直接复用修复后的 pipeline。

## Notes
- 验收目标：`pytest tests -q` 保持 `>= 163 passed`
- 约束目标：`grep "Hunyuan3D-2" model/hunyuan3d/` 与 `grep "hy3dgen" model/hunyuan3d/` 均为空
- 基线：`.venv/bin/python -m pytest tests -q` -> `163 passed in 33.61s`
- 代码检查：`.venv/bin/ruff check model/hunyuan3d/pipeline/shape.py model/hunyuan3d/pipeline/texture.py model/hunyuan3d/provider.py` -> `All checks passed!`
- 最终验收：
  - `.venv/bin/python -m pytest tests -q` -> `163 passed in 33.40s`
  - `grep -R "Hunyuan3D-2" model/hunyuan3d/` -> 无输出
  - `grep -R "hy3dgen" model/hunyuan3d/` -> 无输出
