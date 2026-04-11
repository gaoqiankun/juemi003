# Step1X3D VAE Decode dtype Fix
Date: 2026-03-26
Status: done

Date / Status: 2026-03-26 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
- 修复 ig2mv SDXL 流水线在 VAE 被 upcast 到 float32 后，decode 输入 latents 仍为 float16 导致的 dtype mismatch。
- 增加回归测试，确保 decode 前会对齐 latents dtype 到 VAE 参数 dtype。
- 强化异常日志，记录完整 traceback 便于定位行号。

## Key Decisions
- 先对照 `/tmp/Step1X-3D` 对应实现，优先直接对齐官方写法。
- 最小改动：只在 `vae.decode` 前做 dtype 对齐，不扩散到其他阶段。
- 异常日志改为可输出完整 traceback（`logger.exception` 或携带 `traceback.format_exc()`）。

## Changes
- 已修改：
  - `model/step1x3d/pipeline/step1x3d_texture/pipelines/ig2mv_sdxl_pipeline.py`
    - 新增 `_decode_latents_with_vae_dtype()`，在 decode 前统一执行：
      `latents = latents.to(next(iter(self.vae.post_quant_conv.parameters())).dtype)`
    - 将原 `self.vae.decode(...)` 调用改为通过上述方法解码，覆盖“VAE 已提前 upcast 但 latents 仍为 half”路径。
  - `engine/pipeline.py`
    - `except StageExecutionError` 的 `logger.warning` 增加 `traceback=traceback.format_exc()`。
  - `stages/gpu/stage.py`
    - `except Exception` 的 `logger.warning` 增加 `traceback=traceback.format_exc()`。
  - `tests/test_api.py`
    - 新增回归测试 `test_step1x3d_ig2mv_decode_casts_latents_to_vae_dtype`，mock VAE 并断言 decode 入参 dtype 对齐到 `post_quant_conv` 参数 dtype。

## Notes
- 对照 `/tmp/Step1X-3D/step1x3d_texture/pipelines/ig2mv_sdxl_pipeline.py`：
  - 官方已有同款 dtype 对齐表达式，但仅在 `needs_upcasting` 分支触发；
  - 本次复现路径中 VAE 在前文已被 upcast，`needs_upcasting` 为 false，因此补齐 decode 前的统一对齐。
- 验证通过：
  - `.venv/bin/python -m pytest tests/test_api.py -q -k ig2mv_decode_casts_latents_to_vae_dtype`
  - `.venv/bin/python -m pytest tests -q`
- 结果：`171 passed in 49.11s`
