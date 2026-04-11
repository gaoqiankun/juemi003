# HunYuan3D PaintPipeline 去除 num_inference_steps 参数
Date: 2026-03-24
Status: done

Date / Status: 2026-03-24 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
修复 HunYuan3D 纹理阶段调用参数不兼容问题：`HunYuan3DPaintPipeline` 不再传入 `num_inference_steps`，避免运行时报 `unexpected keyword argument`。

## Key Decisions
- 用户要求先用 `python -c inspect.signature(...)` 确认参数；本地运行环境缺少 `hy3dgen/torch`，该命令无法直接 import。
- 作为替代，直接读取本机已有 HunYuan3D-2 源码（`/Users/gqk/work/3dv/Hunyuan3D-2/hy3dgen/texgen/pipelines.py`）并用 AST 验证 `Hunyuan3DPaintPipeline.__call__` 形参是 `self, mesh, image`，不支持 `num_inference_steps`。
- 保持改动最小：仅移除纹理调用处的 `num_inference_steps`，不改 shape pipeline 参数。

## Changes
- `model/hunyuan3d/provider.py`
  - `_run_single()` 中纹理阶段调用从
    - `self._texture_pipeline(mesh, image=image, num_inference_steps=texture_steps)`
    改为
    - `self._texture_pipeline(mesh, image=image)`
- `tests/test_api.py`
  - 调整 `test_hunyuan3d_provider_run_single_uses_correct_kwargs`：
    - 纹理假管线改为仅接受 `(mesh, image)`。
    - 断言改为只校验 `mesh` 与 `image` 输入，不再期待 `num_inference_steps`。

## Notes
- 参数确认命令执行记录：
  - `python -c "import inspect; from hy3dgen.texgen import Hunyuan3DDiTFlowMatchingPipeline; from hy3dgen.texgen import HunYuan3DPaintPipeline; print(inspect.signature(HunYuan3DPaintPipeline.__call__))"` → 本地缺少依赖，`ModuleNotFoundError`。
  - AST 解析源码结果：`['self', 'mesh', 'image']`。
- 验证：
  - `.venv/bin/python -m pytest tests/test_api.py::test_hunyuan3d_provider_run_single_uses_correct_kwargs -q` → 1 passed
  - 使用 TestClient 提交 HunYuan3D 任务（启用 hunyuan3d + patched provider）→ `status=succeeded`，日志未出现 `unexpected keyword argument`
  - `.venv/bin/python -m pytest tests -q` → 159 passed
