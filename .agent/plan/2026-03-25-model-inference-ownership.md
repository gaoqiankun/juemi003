# Model Inference Ownership — 总体设计
Date: 2026-03-25
Status: planning

## Goal

把三个模型（HunYuan3D-2 / Trellis2 / Step1X-3D）的推理代码内化为自维护代码，
消除对外部 git clone repo 的运行时依赖（`Hunyuan3D-2/`、`/opt/TRELLIS.2`、`/opt/Step1X-3D`）。

---

## 问题现状

| 模型 | 外部依赖方式 | 具体 import |
|------|-------------|-------------|
| HunYuan3D-2 | 本地 clone `Hunyuan3D-2/`（untracked） | `hy3dgen.shapegen`, `hy3dgen.texgen` |
| Trellis2 | Docker clone `/opt/TRELLIS.2` + PYTHONPATH | `trellis2.pipelines`, `o_voxel` |
| Step1X-3D | Docker clone `/opt/Step1X-3D` + PYTHONPATH | `step1x3d_geometry`, `step1x3d_texture` |

痛点：
- 版本不受控，上游随时破坏接口
- 本地开发需要手动 clone + 配 PYTHONPATH
- 无法对推理逻辑做定制化优化
- `Hunyuan3D-2/` 占据仓库工作区，untracked 状态混乱

---

## 目标架构

### 目录结构

```
model/
  base.py                         # 不动（Protocol + 数据类）
  trellis2/
    __init__.py
    provider.py                   # 薄封装，只做加载/调度/进度
    pipeline.py                   # 我们维护的推理实现（参考官方）
    ext/                          # 编译扩展（o_voxel）占位，Phase 1 仍 Dockerfile 编译
  hunyuan3d/
    __init__.py
    provider.py                   # 薄封装
    pipeline/
      __init__.py
      shape.py                    # shape 生成 pipeline（参考 hy3dgen/shapegen）
      texture.py                  # texture 生成 pipeline（参考 hy3dgen/texgen）
  step1x3d/
    __init__.py
    provider.py                   # 薄封装
    pipeline/
      __init__.py
      geometry.py                 # geometry pipeline（参考 step1x3d_geometry）
      texture.py                  # texture pipeline（参考 step1x3d_texture）
    ext/                          # 编译扩展（rasterizer）占位，Phase 1 仍 Dockerfile 编译
```

### 分层原则

```
provider.py
  ├─ from_pretrained()     加载权重 → 构造 pipeline 实例
  ├─ estimate_vram_mb()    静态估算
  ├─ stages property       阶段定义
  ├─ run_batch()           调 pipeline，回传 progress_cb
  └─ export_glb()          trimesh/glb 导出

pipeline/（或 pipeline.py）
  ├─ 只依赖标准 pip 包：torch / diffusers / transformers / accelerate / trimesh 等
  ├─ 不 import 任何外部 repo 路径
  └─ 是本次需要"移入并自维护"的核心
```

### 编译扩展处理（Phase 1）

| 扩展 | 归属 | Phase 1 方案 |
|------|------|-------------|
| `o_voxel` | Trellis2 | Dockerfile 继续从 TRELLIS.2 repo 编译安装，provider 改为 `from o_voxel import ...`（pip 包名不变），但 pipeline 逻辑自维护 |
| Step1X rasterizer | Step1X-3D | 同上，Dockerfile 编译；pipeline.py 通过标准 import 调用，不依赖整个 Step1X repo |

Phase 2 再考虑将编译产物打成 wheel 纳入仓库，彻底去掉 Docker clone。

---

## 验收标准（整体）

- `pytest tests -q` ≥ 163 passed（三个模型全部实现后）
- `ruff check model/` 无新增错误
- `grep -r "from hy3dgen" model/` 零结果
- `grep -r "from trellis2" model/` 零结果
- `grep -r "from step1x3d" model/` 零结果
- Docker build 不再有 `git clone` HunYuan3D-2 / TRELLIS.2 / Step1X-3D 完整 repo（编译扩展的 clone 除外，Phase 1 容忍）

---

## 实施计划

### Phase 1-A：HunYuan3D-2（第一个，最直接）

**任务**：把 `Hunyuan3D-2/hy3dgen/` 中 shape + texture pipeline 的核心推理逻辑
移入 `model/hunyuan3d/pipeline/shape.py` 和 `texture.py`，
`provider.py` 改为 import 我们自己的 pipeline 类。

**输入**：
- 参考 `Hunyuan3D-2/hy3dgen/shapegen/pipelines.py`（`Hunyuan3DDiTFlowMatchingPipeline`）
- 参考 `Hunyuan3D-2/hy3dgen/texgen/pipelines.py`（`Hunyuan3DPaintPipeline`）
- 保持 `provider.py` 对外接口不变（`BaseModelProvider` Protocol）

**约束**：
- pipeline 只 import：torch / diffusers / transformers / accelerate / huggingface_hub / trimesh / Pillow
- 删除官方代码中与本项目无关的功能（CLI、训练代码、评测脚本等）
- `Hunyuan3D-2/` 目录完成后可从 AGENTS.md 规则中移除"不修改"限制

### Phase 1-B：Trellis2

**任务**：把 `trellis2.pipelines` 的推理逻辑移入 `model/trellis2/pipeline.py`，
provider 改为 import 自己的 pipeline；`o_voxel` 的 import 保持（pip 包）。

### Phase 1-C：Step1X-3D

**任务**：把 geometry + texture pipeline 移入 `model/step1x3d/pipeline/`，
rasterizer 编译扩展保持 Dockerfile 方式；provider 改为 import 自己的 pipeline。

---

## Notes

- 每个 Phase 独立 PR，单独验收
- provider.py 外部接口签名全程不变，engine / stages 层无需改动
- mock provider 保持现有实现不动（无外部依赖）
