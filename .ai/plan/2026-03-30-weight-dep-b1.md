# 2026-03-30 · weight-dep-b1
Date: 2026-03-30
Status: done

## 目标
实现 Weight Dependency B1：新增依赖缓存存储层、扩展 WeightManager 与 Admin API，使 pending 模型可返回 deps 字段，并提供依赖查询接口。

## 计划改动文件
- `storage/dep_store.py`（新建）
  - 新增 `DepCacheStore` / `ModelDepRequirementsStore`
  - 服务启动初始化：`dep_cache`、`model_dep_requirements`
- `engine/weight_manager.py`
  - `download()` 签名扩展：`(model_id, provider_type, weight_source, model_path)`
  - provider 依赖读取（B1 空列表回退）
  - per-dep lock + `_download_dep_once`
  - dep 失败错误透传到主模型状态
- `api/server.py`
  - AppContainer 注入 dep stores
  - `POST /api/admin/models` 透传 `provider_type` 到 `WeightManager.download`
  - `GET /api/admin/models?include_pending=true` 为 pending 记录补 `deps` 字段
  - 新增 `GET /api/admin/deps`
  - 新增 `GET /api/admin/models/{id}/deps`
- `tests/test_api.py`
  - 补充 deps 字段与新 API 行为测试
- `tests/test_worker.py`（如需）
  - 若 `WeightManager.download` 签名改动影响 monkeypatch/调用点，补齐兼容
- `.ai/pending.md`
  - 记录 API 变化

## 启动检查记录
- 已阅读：`AGENTS.md`、`.ai/roles/backend.md`、`.ai/impact-map.md`、`.ai/plan/2026-03-29-weight-dependency-design.md`
- 基线测试：`.venv/bin/python -m pytest tests -q` 当前环境失败（`.venv` 缺少 `pytest` 模块，且 `.venv/bin/python` 无 `pip`）

## 风险
- `api/server.py` 已超大文件；本次按上游任务要求在现有文件内最小增量修改。

## 实际改动
- `storage/dep_store.py`（新建，283 行）
  - 新增 `dep_cache`、`model_dep_requirements` 表
  - 新增 `DepCacheStore`：`get_or_create`、`update_status`、`update_progress`、`update_done`、`update_error`、`get_all_for_model`、`list_all`、`get`
  - 新增 `ModelDepRequirementsStore`：`link`、`get_dep_ids_for_model`
  - 并发安全点：`INSERT OR IGNORE + SELECT`，并在写路径加 `asyncio.Lock`
- `engine/weight_manager.py`
  - `download()` 签名改为 `(model_id, provider_type, weight_source, model_path)`
  - 下载主模型后读取 provider 依赖（`getattr(provider_cls, "dependencies", lambda: [])()` 回退）
  - 新增 per-dep lock + `_download_dep_once`，共享依赖只下载一次
  - 依赖下载使用 `snapshot_download(repo_id=..., local_dir=None)`，把返回 snapshot path 写入 `resolved_path`
  - 依赖失败时抛出 `dep_{dep_id}: {reason}`，主模型落库为 `error`
- `api/server.py`
  - AppContainer 注册 `dep_cache_store`、`model_dep_requirements_store`
  - lifespan 启动时自动建新表（兼容旧库启动）
  - `POST /api/admin/models` 支持 `provider_type`（兼容 `providerType/providerName`），并透传给 `WeightManager.download`
  - `GET /api/admin/models?include_pending=true` 增加 `deps` 字段（数组）
  - 新增 `GET /api/admin/deps`
  - 新增 `GET /api/admin/models/{id}/deps`
- `tests/test_api.py`
  - 同步 `weight_manager.download` monkeypatch 签名
  - 断言 pending 模型返回 `deps: []`
  - 覆盖 `GET /api/admin/deps`、`GET /api/admin/models/{id}/deps` 空列表场景
  - 新增 `provider_type`（snake_case）兼容测试
- `.ai/pending.md`
  - 已登记前端待适配 API contract

## 验收结果
- `uv run python -m pytest tests -q`：`181 passed, 1 failed`
  - 失败用例：`tests/test_api.py::test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu[asyncio]`
  - 该失败与本次 B1 变更无直接耦合（本次未改 `model/trellis2/provider.py`）
- `uv run ruff check .`：失败（仓库存在大量存量 lint 问题，当前输出 `Found 213 errors`）
- 针对本次新实现核心文件执行：
  - `uv run python -m ruff check storage/dep_store.py engine/weight_manager.py`
  - 结果：`All checks passed!`

## API Contract 记录
- 已更新 `.ai/pending.md`：
  - `GET /api/admin/models?include_pending=true` 新增 `deps` 数组字段
  - 新增 `GET /api/admin/deps`
  - 新增 `GET /api/admin/models/{id}/deps`
