# Step1X3D Geometry Transformer dtype 对齐
Date: 2026-03-26
Status: done

Date / Status: 2026-03-26 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
- 在 geometry denoising loop 中，确保传入 transformer 的 latent 与条件 tensor dtype 与 transformer 权重 dtype 一致，避免 linear/bias dtype mismatch。

## Key Decisions
- 官方仓库同位置未显式做该防护；在内化版本补充最小显式 cast 保护。
- cast 仅发生在 transformer forward 前，不改变其他模块原有 dtype 路径。

## Changes
- 已修改：
  - `model/step1x3d/pipeline/step1x3d_geometry/models/pipelines/pipeline.py`
    - 在 denoising loop 前读取 `transformer_dtype = next(self.transformer.parameters()).dtype`。
    - 在进入 `self.transformer(...)` 前，将 `latent_model_input`、`visual_condition`、`label_condition`、`caption_condition` 显式 cast 到 `transformer_dtype`。
  - `tests/test_api.py`（新增回归测试）
    - 新增 `test_step1x3d_geometry_casts_transformer_inputs_to_transformer_dtype`，验证 transformer 前输入 dtype 会对齐到参数 dtype。

## Notes
- 验证通过：`.venv/bin/python -m pytest tests -q`
- 结果：`170 passed in 33.23s`
