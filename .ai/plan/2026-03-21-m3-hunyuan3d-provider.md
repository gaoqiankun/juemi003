# M3 · HunYuan3D-2 Provider
Date: 2026-03-21
Status: done

## Goal
实现 HunYuan3D-2 Provider（mock + real），接入现有 provider 框架，支持通过 `MODEL_PROVIDER=hunyuan3d` 环境变量切换。

## Key Decisions
- **复用 3 个 canonical stages**（ss / shape / material）：HunYuan3D-2 内部是 2 阶段（shape gen + texture paint），但对外 emit 相同的 3 stage 名称，避免修改 pipeline / TaskStatus / API schema / 前端
- **Real provider 依赖 `hy3dgen` 包**：shape 用 `Hunyuan3DDiTFlowMatchingPipeline`，texture 用 `Hunyuan3DPaintPipeline`（可选，缺失时跳过 texture）
- **GLB 导出**：HunYuan3D-2 输出 trimesh 对象，直接调用 `mesh.export()` 而非 Trellis2 的 `o_voxel` 路径
- **Mock provider** 和 MockTrellis2Provider 行为一致：同样支持故障注入、可配置延迟

## Changes
- `model/hunyuan3d/provider.py`：从 stub 扩展为完整实现
  - `MockHunyuan3DProvider`：mock 推理 + GLB 输出 + 故障注入
  - `Hunyuan3DProvider`：real 推理，双 pipeline 架构（shape + texture）
  - `_inspect_runtime()`：检测 torch / CUDA / hy3dgen 可用性
  - `_resolve_model_reference()`：本地路径 vs HuggingFace ID
- `api/server.py`：`build_provider()` 新增 `hunyuan3d` 分支
- `stages/gpu/worker.py`：`_build_process_provider()` 新增 `hunyuan3d` 分支
- `tests/test_api.py`：新增 11 个测试用例覆盖 mock/real provider 行为

## Notes
- 测试基线：96 passed（原 85 + 新增 11）
- Real provider 未在 GPU 环境验证（需要 `hy3dgen` 包 + CUDA），mock 模式可立即使用
- 前端 admin-mocks.ts 和 i18n 已有 HunYuan3D 选项，无需额外改动
