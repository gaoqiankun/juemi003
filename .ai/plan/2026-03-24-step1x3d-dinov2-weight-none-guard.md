# Step1X-3D DINOv2 _init_weights 兼容新版 transformers
Date: 2026-03-24
Status: done

Date / Status: 2026-03-24 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
在 `docker/trellis2/Dockerfile` 中对 Step1X-3D 的 DINOv2 encoder 代码加 `module.weight is None` 防护，避免新版 transformers 触发 `_init_weights` 时因 `weight=None` 报 `AttributeError`。

## Key Decisions
- 补丁放在 `git clone Step1X-3D` 之后、Step1X 依赖安装之前，确保后续安装/导入使用的是已修复代码。
- 使用 Dockerfile 内嵌 Python 脚本按代码结构定位并插入 guard，而不是依赖固定行号。
- 保持幂等：若上游已包含 guard，则输出提示并直接退出成功，不中断构建。

## Changes
- `docker/trellis2/Dockerfile`
  - 在 `RUN git clone https://github.com/stepfun-ai/Step1X-3D /opt/Step1X-3D` 后新增 patch 步骤：
    - 目标文件：`/opt/Step1X-3D/step1x3d_geometry/models/conditional_encoders/dinov2_with_registers/modeling_dinov2_with_registers.py`
    - 在 `if isinstance(module, (nn.Linear, nn.Conv2d)):` 分支中、`module.weight.data = nn.init.trunc_normal_(` 前插入：
      - `if module.weight is None:`
      - `    return`

## Notes
- 通过代码检查确认：
  - 补丁步骤位于 Step1X clone 之后、Step1X 相关依赖安装之前，满足执行顺序要求。
  - 补丁目标文件与用户指定路径一致，导入路径 `step1x3d_geometry.models.pipelines.pipeline` 使用该源码树。
- 本机无法直接执行 Docker 构建（缺少 `docker` 命令），未在容器内实跑 import。
- 回归验证：
  - `.venv/bin/python -m pytest tests -q` → `161 passed`
