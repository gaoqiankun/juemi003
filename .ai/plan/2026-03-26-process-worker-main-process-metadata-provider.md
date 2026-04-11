# ProcessGPUWorker 主进程模型双重加载消除
Date: 2026-03-26
Status: done

Date / Status: 2026-03-26 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
在 `provider_mode=real` 且使用 `ProcessGPUWorker` 的路径下，主进程不再通过 `from_pretrained()` 加载完整模型权重，避免与子进程重复占用 GPU 显存。

## Key Decisions
- 主进程保留 `ModelRuntime.provider`，但改为 real provider 的 metadata-only 轻量实例。
- 轻量实例仅负责 `stages`、`estimate_vram_mb()`、`export_glb()`，不承载推理权重。
- Mock 模式保持不变，继续沿用现有 `Mock*Provider` 行为。

## Changes
- `api/server.py`
  - `build_provider()` 在 `provider_mode="real"` 下改为返回 real provider 的 `metadata_only()` 实例，不再在主进程触发 `from_pretrained()`。
- `model/trellis2/provider.py`
  - 新增 `Trellis2Provider.metadata_only(model_path)`，仅解析模型引用，不加载 pipeline/权重。
  - `run_batch()` 在 metadata-only 实例上显式报错，防止误用到主进程推理。
- `model/hunyuan3d/provider.py`
  - 新增 `Hunyuan3DProvider.metadata_only(model_path)`，主进程仅保留导出与元信息能力。
  - `run_batch()` 在 metadata-only 实例上显式报错，防止误用。
- `model/step1x3d/provider.py`
  - 新增 `Step1X3DProvider.metadata_only(model_path)`，不加载 geometry/texture pipeline。
  - `run_batch()` 在 metadata-only 实例上显式报错。
  - `_run_single()` 中 `torch.cuda.empty_cache()` 改为可选导入，避免无 torch 环境测试失败。
- `tests/test_api.py`
  - 新增 real 模式 `build_provider()` 使用 `metadata_only()` 的覆盖（trellis2/hunyuan3d/step1x3d）。
  - 新增 Step1X metadata-only provider 拒绝推理调用的用例。

## Notes
- 结果验证：
  - `.venv/bin/python -m pytest tests -q` → `167 passed`
  - 关键子集：`tests/test_api.py -k "build_provider_uses_ or metadata_only_provider or run_single_calls_both_pipelines"` → `5 passed`
- `ProcessGPUWorker` 子进程路径未改：`stages/gpu/worker.py::_build_process_provider()` 仍在子进程调用各 provider 的 `from_pretrained()`，确保真实推理不变。
- 本次为局部修复，涉及历史超大文件（`api/server.py`、`model/step1x3d/provider.py`、`model/trellis2/provider.py`、`tests/test_api.py`）仅做最小改动，未扩展结构性重构范围。
