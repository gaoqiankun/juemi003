# Model Inference Self-Hosted（Phase 1）
Date: 2026-03-25
Status: planning

## Goal
将三个模型的推理代码内化进仓库，消除运行时对外部 git clone 的依赖。
Phase 1：以官方代码为参考，移入并清理；后续 Phase 2 再做更深层架构优化。

## 现状问题
- `Hunyuan3D-2/`、`/opt/TRELLIS.2`、`/opt/Step1X-3D` 在 Docker 中 clone，通过 `PYTHONPATH` 注入
- 版本不受控、无法审计、无法定制
- 三个模型 provider 直接 import 外部 repo 模块（`hy3dgen.*`、`trellis2.*`、`step1x3d_geometry.*`）

## 目标状态（Phase 1 完成后）
- 所有 `model/` 目录下的代码只 import 标准 pip 包（torch / diffusers / transformers 等）及我们自己的模块
- C++/CUDA 扩展源码移入仓库，Dockerfile 从本地编译而非从外部 clone 编译
- `PYTHONPATH` 中不再有外部 repo 路径
- 测试基线不下降

## 目录结构

```
model/
  base.py                          # Protocol（不动）
  hunyuan3d/                       ✅ Phase 1 已完成
    pipeline/
      shape.py
      texture.py
    provider.py
  trellis2/
    pipeline/                      ← 从 TRELLIS.2/trellis2/pipelines/ 移入，清理
      __init__.py
      image_to_3d.py               主 pipeline
      samplers/                    采样器模块
      （其他 pipeline 支撑模块）
    ext/
      o-voxel/                     ← 从 TRELLIS.2/o-voxel 整个目录移入（含 C++/CUDA src）
    provider.py                    → import 我们的 pipeline
  step1x3d/
    pipeline/                      ← 从 Step1X-3D 移入，清理
      geometry.py                  Step1X3DGeometryPipeline
      texture.py                   Step1X3DTexturePipeline
      （支撑模块：ig2mv、mesh util 等）
    ext/
      custom_rasterizer/           ← 从 Step1X-3D/step1x3d_texture/custom_rasterizer 移入
      differentiable_renderer/     ← 从 Step1X-3D/step1x3d_texture/differentiable_renderer 移入
    provider.py                    → import 我们的 pipeline
```

## 分层原则

```
provider.py（薄包装，实现 BaseModelProvider Protocol）
  └─ 调用 pipeline/（推理逻辑，只 import 标准 pip 包 + ext/）
       └─ 依赖 ext/（编译安装的 C++/CUDA 扩展，import 路径不变）
```

## 编译扩展处理

| 扩展 | 来源 | Phase 1 做法 |
|------|------|------------|
| `o_voxel` | TRELLIS.2/o-voxel | 移入 `model/trellis2/ext/o-voxel/`，Dockerfile 从本地 pip install |
| `custom_rasterizer_kernel` | Step1X-3D/step1x3d_texture/custom_rasterizer | 移入 `model/step1x3d/ext/custom_rasterizer/`，Dockerfile 从本地编译 |
| `differentiable_renderer` | Step1X-3D/step1x3d_texture/differentiable_renderer | 移入 `model/step1x3d/ext/differentiable_renderer/`，Dockerfile 从本地编译 |

不内化（继续 pip install）：
- `nvdiffrast`、`nvdiffrec`、`CuMesh`、`FlexGEMM`（第三方，非模型自身代码）
- `torch`、`diffusers`、`transformers`、`accelerate`、`trimesh`、`rembg` 等通用包
- `pytorch-lightning`、`jaxtyping`、`utils3d` 等 Step1X 运行依赖

## Dockerfile 变更方向
- 删除 `git clone` 外部 repo 的步骤
- 改为从 `model/<name>/ext/` 编译安装扩展
- 删除 `PYTHONPATH` 中的外部 repo 路径
- 三个模型目前共用 `docker/trellis2/Dockerfile`，Phase 1 保持结构不变，只改 build 源

## 实现顺序

| 步骤 | 内容 | 状态 |
|------|------|------|
| Step 1 | HunYuan3D-2 pipeline 移入 | ✅ done |
| Step 2 | Trellis2：pipeline 移入 + o-voxel ext 移入 + Dockerfile 更新 | 🔲 |
| Step 3 | Step1X-3D：pipeline 移入 + 两个 ext 移入 + Dockerfile 更新 | 🔲 |

## Key Decisions

| 决策 | 原因 |
|------|------|
| ext/ 放在 model/<name>/ 下 | 扩展与模型强绑定，co-located 便于维护 |
| 编译扩展安装后保持原 import 名不变 | 最小改动 provider；Phase 2 再统一命名空间 |
| 不内化第三方 lib | 非模型自身逻辑，随 upstream 更新对我们有利 |
| Phase 1 只做移入+清理，不重设计 | 先建立 ownership，再优化；避免一步改太多引入风险 |

## Notes
- 验收基线：`pytest tests -q` ≥ 163 passed
- Dockerfile 改动需在 Docker 环境实际构建验证（本地测试跑 mock）
