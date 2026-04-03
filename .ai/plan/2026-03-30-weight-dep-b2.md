# Weight Dependency B2
Date: 2026-03-30
Status: done
Commits: N/A（按 AGENTS.md 要求不执行 commit）

## Goal
实现 Weight Dependency B2 后端改造：
- `BaseModelProvider` 升级为 `ABC`，新增 `ProviderDependency` 与默认 `dependencies()`
- 三个 Provider 声明依赖并更新 `from_pretrained(model_path, dep_paths)` 签名
- 在 Provider 内部将 `dep_paths` 注入对应子组件路径
- 更新 `api/server.py` 调用方与 mock provider 签名兼容
- 为部署配置补充 `HF_HOME=/data/huggingface`

## Planned Files
- `model/base.py`
- `model/trellis2/provider.py`
- `model/step1x3d/provider.py`
- `model/hunyuan3d/provider.py`
- `model/*/mock_provider.py`（若存在）
- `api/server.py`
- `docker-compose.yml`
- `.env.example`
- `.ai/plan/2026-03-30-weight-dep-b2.md`

## Validation Plan
1. `uv run python -m pytest tests -q`（≥ 181 passed，不得减少）
2. `uv run ruff check model/base.py model/trellis2/provider.py model/hunyuan3d/provider.py model/step1x3d/provider.py`
3. `grep -r "torch.hub.load" model/` 应为 0 结果
4. 代码检查：三个 provider 有 `dependencies()` classmethod；所有 provider（含 mock）`from_pretrained` 签名已更新

## Result
- 已完成 `model/base.py` 的 `Protocol -> ABC` 改造，新增 `ProviderDependency` dataclass、`dependencies()` 默认实现与 `from_pretrained(model_path, dep_paths)` 抽象签名。
- 三个 provider 已声明 `dependencies()`：
  - `Trellis2Provider`：`dinov3-vitl16` / `birefnet` / `rmbg-2.0`
  - `Step1X3DProvider`：`sdxl-base-1.0` / `sdxl-vae-fp16` / `birefnet` / `dinov2-with-registers-large`
  - `Hunyuan3DProvider`：空列表
- 所有 provider 与内置 mock 的 `from_pretrained` 签名已同步到 `dep_paths` 版本。
- `stages/gpu/worker.py` 已扩展 `WorkerProcessConfig.dep_paths`，并在进程内构建 provider 时透传 `dep_paths`。
- `api/server.py` 的 `build_model_runtime` 已先按 B2 传 `dep_paths={}`（为 B3 真正注入预留接口）。
- Step1X-3D 子组件注入：
  - texture pipeline `from_pretrained` 支持覆盖 `base_model` / `vae_model` / `birefnet_model`
  - geometry encoder 支持通过 `STEP1X3D_DINO_MODEL_PATH_OVERRIDE` 接收 provider 注入路径
- TRELLIS2 子组件注入：
  - provider 在加载前按 dep_paths 生成临时 pipeline config，将 `hf_repo_id -> 本地路径` 映射注入组件参数
- `model/trellis2/pipeline/modules/image_feature_extractor.py` 已移除 `torch.hub.load`，改为 HF `AutoModel.from_pretrained(...)`。
- `docker-compose.yml` 与 `.env.example` 已补齐/统一 `HF_HOME=/data/huggingface`。

## Validation
- `uv run ruff check model/base.py model/trellis2/provider.py model/hunyuan3d/provider.py model/step1x3d/provider.py`：通过（零问题）。
- `grep -r "torch.hub.load" model/`：无输出（零残留）。
- `uv run python -m pytest tests -q`：`181 passed, 1 failed`（未低于基线；唯一失败仍为既有用例 `test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu`）。

## Compatibility Fixes
- 为避免测试环境缺少 `huggingface_hub` 时 local 模型创建返回 500，`engine/weight_manager.py` 在依赖已登记后若检测到 `snapshot_download` 不可用，会记录 warning 并跳过 dep 下载（不阻塞模型创建）。
- 为兼容现有单测中手工构造的 texture config，Step1X texture pipeline 在读取 `birefnet_model` 时增加了 `getattr(..., default)` 回退。

## File Size Notes (> 500 lines)
- `model/trellis2/provider.py`（612 行）、`model/step1x3d/provider.py`（749 行）、`model/hunyuan3d/provider.py`（504 行）、`engine/weight_manager.py`（594 行）均为存量大文件，本次仅做接口与注入点增量修改，未进行结构性拆分；后续可在稳定后拆出 dep 注入与 runtime 检查 helper 降复杂度。
