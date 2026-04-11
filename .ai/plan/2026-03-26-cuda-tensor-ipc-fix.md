# CUDA Tensor IPC Fix
Date: 2026-03-26
Status: done

Date / Status: 2026-03-26 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
- 修复 GPU 子进程通过 multiprocessing queue 回传结果时包含 CUDA tensor 导致 `pidfd_getfd: Operation not permitted` 的问题。
- 确保 TRELLIS2 返回 `GenerationResult` 前不残留 CUDA tensor。
- 检查并覆盖 Step1X-3D / HunYuan3D 同类风险。

## Key Decisions
- 优先在 provider 返回边界清理 tensor（`detach().cpu()` / numpy），避免跨进程传 CUDA tensor。
- 若 worker 传输层无统一防护，补一个通用兜底，最小侵入保证队列负载可安全 pickle。
- 为修复路径补充回归测试并跑全量 pytest。

## Changes
- 已修改：
  - `model/trellis2/provider.py`
    - `run_batch()` 在构造 `GenerationResult` 前，对 `mesh` 与 `metadata` 执行递归 CPU 化（tensor-like 统一 `detach().cpu()`）。
    - 新增 `_move_tensors_to_cpu()` / `_detach_tensor_like_to_cpu()`，覆盖 dict/list/tuple/set 及对象属性（`__dict__` / `__slots__`）中的 tensor-like 值。
  - `stages/gpu/worker.py`
    - 子进程回传结果前不再裸传：`response_queue.put(..., "results": _sanitize_generation_results_for_ipc(results))`。
    - 新增 `_sanitize_generation_results_for_ipc()` 及递归 CPU 化 helper，作为传输层兜底，防止任意 provider 漏出 CUDA tensor。
  - `tests/test_api.py`
    - 新增 `test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu`，验证 TRELLIS2 provider 返回前会将 mesh 内 tensor-like 移到 CPU。
  - `tests/test_worker.py`
    - 新增 `test_sanitize_generation_results_for_ipc_moves_tensor_like_objects_to_cpu`，验证 worker 传输层兜底会清理 `GenerationResult` 的 mesh/metadata 中 CUDA tensor-like。

## Notes
- 根因确认：
  - `model/trellis2/provider.py::_run_single()` 返回 `Trellis2ImageTo3DPipeline.run()[0]`，该对象（`MeshWithVoxel`）包含 `vertices/faces/coords/attrs` torch tensor，默认仍在 CUDA。
  - `stages/gpu/worker.py` 原实现将 `results` 直接 `queue.put`，无 CPU 化处理；在 Docker 默认 syscall 策略下会触发 CUDA IPC (`pidfd_getfd`) 失败。
- Step1X-3D / HunYuan3D 检查结论：
  - 两者 `run_batch()` 主路径返回值来源为 mesh/trimesh 对象（非 CUDA tensor 容器），未发现同类“结果对象残留 CUDA tensor”路径；因此未改 provider 代码。
  - 同时 worker 传输层兜底已覆盖全部 provider，防止未来回归。
- 验证通过：
  - `.venv/bin/python -m pytest tests/test_api.py -q -k trellis2_provider_run_batch_moves_mesh_tensors_to_cpu`
  - `.venv/bin/python -m pytest tests/test_worker.py -q`
  - `.venv/bin/python -m pytest tests -q`
- 结果：`173 passed in 33.05s`
