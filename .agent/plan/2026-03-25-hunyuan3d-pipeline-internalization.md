# Hunyuan3D Pipeline Internalization
Date / Status: 2026-03-25 / done / Commits:

## Goal
将 HunYuan3D-2 provider 的 shape / texture 推理入口从外部 `hy3dgen` 依赖迁移到仓库内自维护实现，并保持 provider 对外接口不变。

## Key Decisions
- 在 `model/hunyuan3d/pipeline/` 新建 `shape.py`、`texture.py` 与 `__init__.py`，集中承载运行时推理入口类。
- `model/hunyuan3d/provider.py` 仅切换 pipeline import 与 runtime 检查路径，不调整 mock provider 与 BaseModelProvider 协议签名。
- 只保留推理所需逻辑（模型路径解析、pipeline 加载、推理调用参数映射），不引入训练/评测/CLI 代码。

## Changes
- 新增：
  - `model/hunyuan3d/pipeline/__init__.py`
  - `model/hunyuan3d/pipeline/shape.py`
  - `model/hunyuan3d/pipeline/texture.py`
- 修改：
  - `model/hunyuan3d/provider.py`
    - real provider runtime 自检不再动态 import `hy3dgen.*`
    - 改为引用仓库内 `model.hunyuan3d.pipeline` 的 shape/texture pipeline 类
    - 对外协议与 mock provider 保持不变

## Notes
- 开工前基线：`.venv/bin/python -m pytest tests -q` -> `163 passed`。
- 验证结果：
  - `.venv/bin/ruff check model/hunyuan3d/` -> `All checks passed!`
  - `grep -r "from hy3dgen" model/` -> 无结果
  - `grep -r "import hy3dgen" model/` -> 无结果
  - `.venv/bin/python -m pytest tests -q` -> `163 passed`
