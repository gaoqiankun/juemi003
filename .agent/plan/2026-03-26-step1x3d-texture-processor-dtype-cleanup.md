# Step1X3D Texture Processor dtype 清理
Date / Status: 2026-03-26 / done / Commits: N/A（按仓库规范本次不执行提交）

## Goal
- 移除内化版本在 `prepare_ig2mv_pipeline` 中对 `module.processor` 的额外 dtype cast，对齐官方行为，降低精度/兼容性风险。

## Key Decisions
- 以官方 `/tmp/Step1X-3D` 为准：保留 `pipe.to` 与 `cond_encoder.to`，移除额外 processor `.to(device, dtype=...)` 循环。
- 通过回归测试验证不会再触发 processor 级别 dtype 强转。

## Changes
- 已修改：
  - `model/step1x3d/pipeline/step1x3d_texture/pipelines/step1x_3d_texture_synthesis_pipeline.py`
    - `prepare_ig2mv_pipeline()` 中移除了 `module.processor.to(device=device, dtype=dtype)` 的额外循环，仅保留官方同款的 `pipe.to(...)` 与 `pipe.cond_encoder.to(...)`。
  - `tests/test_api.py`（新增回归测试）
    - 新增 `test_step1x3d_texture_load_ig2mv_pipeline_does_not_cast_processor_dtype`，验证不再触发 processor 级别 dtype cast。

## Notes
- 验证通过：`.venv/bin/python -m pytest tests -q`
- 结果：`170 passed in 33.23s`
