# Step1X-3D pytorch3d 显式安装与 workaround 回退
Date: 2026-03-26
Status: done

Date / Status: 2026-03-26 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
在 Dockerfile 显式安装 pytorch3d，并撤销 provider/test 中的 pytorch3d 缺失降级 workaround，恢复 texture pipeline 常规加载路径。

## Key Decisions
- 不在 provider 层继续做 `pytorch3d` 缺失降级，恢复 texture pipeline 原始加载语义。
- 依赖层面通过 Docker builder 显式安装 `pytorch3d` 预编译 wheel（py311/cu124/torch2.6）。
- `model/step1x3d/pipeline/__init__.py` 与 `step1x3d_geometry/__init__.py` 继续保持当前 lazy 状态，不做改动。

## Changes
- 修改 `docker/trellis2/Dockerfile`：
  - 在 torch 相关 Python 依赖安装之后、`COPY model/...` 之前，新增 `pytorch3d` wheel 安装命令（带 `--extra-index-url`）。
- 回退确认：
  - `model/step1x3d/provider.py` 已无 `_is_missing_pytorch3d_dependency`、`_iter_exception_chain`，`_inspect_runtime` 恢复 texture pipeline 原始 `try/except ModuleNotFoundError: pass` 导入方式。
  - `tests/test_api.py` 已撤销 3 个 workaround 测试，测试总数恢复到 163。

## Notes
- 基线：`.venv/bin/python -m pytest tests -q` -> `166 passed in 32.85s`（含 workaround 测试）
- 验收：
  - `.venv/bin/python -m pytest tests -q` -> `163 passed in 33.55s`
  - `bash -n docker/trellis2/Dockerfile` 通过
