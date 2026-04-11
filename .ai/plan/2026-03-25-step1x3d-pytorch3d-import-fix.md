# Step1X-3D pytorch3d 导入链修复
Date: 2026-03-25
Status: done

Date / Status: 2026-03-25 / done / Commits: N/A（按仓库规范本次不执行提交）
## Goal
定位并修复 Step1X-3D 在模型加载阶段触发 `No module named 'pytorch3d'` 的问题，保证推理链路可用并支持 texture pipeline 可选降级。

## Key Decisions
- 结论为**混合场景**：`pytorch3d` 仅是 **texture 推理链路必需依赖**，geometry 推理链路不依赖。
- 不在 Docker 强制安装 `pytorch3d`（避免对当前镜像和 CUDA/torch 轮子组合引入额外不确定性），而是在 provider 层实现“缺失时仅降级 texture”。
- 保持 `model/step1x3d/pipeline/__init__.py` 与 `step1x3d_geometry/__init__.py` 的 lazy 状态，不恢复 eager import。

## Changes
- 调查 `pytorch3d` import 位置（`model/step1x3d/`）：
  - **模块级 import**：  
    - `pipeline/step1x3d_texture/texture_sync/project.py`  
    - `pipeline/step1x3d_texture/texture_sync/geometry.py`  
    - `pipeline/step1x3d_texture/texture_sync/shader.py`
  - **函数内 import**：  
    - `pipeline/step1x3d_texture/texture_sync/project.py:UVProjection.load_glb_mesh` (`pytorch3d.io.experimental_gltf_io`)
- 从 provider 常量追踪 import 链：
  - geometry：`provider._GEOMETRY_PIPELINE_MODULE -> ...step1x3d_geometry.models.pipelines.pipeline`（链路内无 `pytorch3d`）
  - texture：`provider._TEXTURE_PIPELINE_MODULE -> ...step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline -> ...ig2mv_sdxl_pipeline -> ...texture_sync.project -> ...texture_sync.{geometry,shader}`（模块级触发 `pytorch3d`）
- 修复 `model/step1x3d/provider.py`：
  - 在 `_inspect_runtime` 中先探测 `importlib.util.find_spec(\"pytorch3d\")`。
  - 当缺失 `pytorch3d` 时，直接跳过 texture pipeline，并记录 `texture_pipeline_skip_reason`。
  - 当 texture import/load 抛 `ModuleNotFoundError` 时，仅对 `pytorch3d*` 依赖缺失降级；其它缺失依赖继续抛 `ModelProviderConfigurationError`。
  - 新增 `_is_missing_pytorch3d_dependency()` 与 `_iter_exception_chain()`，用于识别嵌套异常链中的缺失模块。
- 新增测试（`tests/test_api.py`）：
  - 缺失 `pytorch3d` 时仍可加载 geometry pipeline。
  - texture load 阶段才触发缺失 `pytorch3d` 时也能降级。
  - texture import 若缺失的是非可选依赖，必须报配置错误（防静默吞错）。

## Notes
- 基线：`.venv/bin/python -m pytest tests -q` -> `163 passed in 34.00s`
- 验收：`.venv/bin/python -m pytest tests -q` -> `166 passed in 33.64s`
- 文件体积说明：`model/step1x3d/provider.py` 为存量大文件（>500 行），本次仅局部增量修复导入降级逻辑，未做拆分以避免影响现有 provider 行为。
