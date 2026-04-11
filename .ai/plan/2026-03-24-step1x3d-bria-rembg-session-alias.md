# Step1X-3D rembg bria session 兼容修复
Date: 2026-03-24
Status: done

Date / Status: 2026-03-24 / planning→done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
修复 Step1X-3D 推理阶段报错 `No session class found for model 'bria'`，使 GPU 阶段可继续执行而不是直接失败。

## Key Decisions
- 不改业务架构，按执行者职责在 provider 层做兼容补丁，避免强依赖第三方仓库版本。
- 在 `Step1X3DProvider` 启动/推理路径中安装一次性 monkey patch：将 rembg 的 `model_name="bria"` 映射为 `bria-rmbg`。
- 若运行环境同时不支持 `bria-rmbg`，再回退到 rembg 默认 session（通常是 `u2net`），优先保证任务可跑通。
- 补丁保持幂等（已安装不重复 patch），并同步 `rembg.bg.new_session` 别名以覆盖不同 rembg 版本导出路径。

## Changes
- `model/step1x3d/provider.py`
  - 新增 `_install_rembg_bria_alias_patch()` 及辅助函数：
    - `_extract_requested_session_model_name(...)`
    - `_replace_session_model_name(...)`
    - `_drop_session_model_name(...)`
  - 在 `_inspect_runtime(...)` 与 `_run_single(...)` 中调用补丁安装，确保真实推理路径生效。
- `tests/test_api.py`
  - 新增 `test_step1x3d_provider_patches_rembg_bria_alias`：验证 `bria -> bria-rmbg` 映射生效。
  - 新增 `test_step1x3d_provider_rembg_bria_alias_falls_back_to_default_session`：验证 `bria-rmbg` 不可用时回退默认 session。

## Notes
- 回归验证：
  - `pytest tests/test_api.py -k "step1x3d_provider_patches_rembg_bria_alias or step1x3d_provider_rembg_bria_alias_falls_back_to_default_session or step1x3d_provider_run_single_calls_both_pipelines" -q` → `3 passed`
  - `pytest tests -q` → `163 passed`
- 本次未执行 git 提交（遵循 `gen3d/AGENTS.md`）。
