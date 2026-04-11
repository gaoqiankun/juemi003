# Step1X3D BiRefNet dtype 回归修复
Date: 2026-03-26
Status: done

Date / Status: 2026-03-26 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
- 以最小改动修复 Step1X3D texture pipeline 在 remove_bg 路径的 dtype 强制转换问题，避免 `Half` 输入与 `float` bias 不匹配。

## Key Decisions
- 对齐官方实现，只移除两处额外 dtype 参数，不调整其他逻辑。
- 新增回归测试通过 mock 断言 `.to()` 调用参数，覆盖 remove_bg / BiRefNet 路径。

## Changes
- 已修改：
  - `model/step1x3d/pipeline/step1x3d_texture/pipelines/step1x_3d_texture_synthesis_pipeline.py`
    - `remove_bg()`：`input_images.to(...)` 移除 dtype 参数，仅保留 device。
    - `__call__()`：BiRefNet `to(...)` 移除 dtype 参数，仅保留 device。
  - `tests/test_api.py`
    - 新增 `test_step1x3d_texture_remove_bg_path_does_not_force_dtype`：
      - 验证 `remove_bg` 路径的输入 tensor `.to()` 不带 `dtype`。
      - 验证 BiRefNet `.to()` 仅传 `device`，不传 `dtype`。

## Notes
- 验证通过：
  - `.venv/bin/python -m pytest tests -q`
  - 结果：`168 passed in 33.43s`
