# 模型配置全部从 model_definitions 表读取，移除 MODEL_PATH 和 MODEL_PROVIDER
Date: 2026-03-23
Status: done
Commits: N/A（按 AGENTS.md，本轮不执行 commit）

## Goal
当前 `build_provider()` 和 `build_model_runtime()` 从全局环境变量获取模型配置：
- `MODEL_PATH`（`config.model_path`）：所有 provider 共用一个值，但每个 provider 需要不同的 HF repo ID
- `MODEL_PROVIDER`（`config.model_provider`）：指定使用哪个 provider

`model_definitions` 表已经存储了每个模型的 `model_path`、`provider_type`、`is_default`，但运行时完全没有使用。本轮重构让所有模型配置从数据库读取，移除两个冗余的全局环境变量。

## Key Decisions
- `build_model_runtime()` 从 `ModelStore` 查询 `model_path` 和 `provider_type`
- `build_provider()` 签名改为接收独立参数，不再接收整个 config
- `config.py` 中删除 `model_path` 和 `model_provider` 两个字段
- 启动时预热模型从 `model_definitions` 查 `is_default=1` 的记录，替代硬编码 `startup_models=("trellis",)`
- Settings API 的 defaultProvider fallback 改为查 `is_default=1`
- Docker 配置：移除 `MODEL_PATH`、`MODEL_PROVIDER`、`MODEL_DIR` 卷挂载；添加 `HF_TOKEN` 透传
- 为兼容历史请求里的 `model=\"trellis\"`，`build_model_runtime()` 在查不到 `trellis` 时回退到当前 default model（其余模型名查不到仍报错）

## Changes
- `config.py`：删除 `model_path` 和 `model_provider` 字段
- `api/server.py`：
  - `build_provider()` 改为接收独立参数
  - `build_model_runtime()` 改为 async，从 `model_store.get_model()` 查配置
  - `ModelRegistry` runtime loader 改为 async 函数，避免 coroutine 通过线程中转导致未 await 警告
  - `create_app()` 中启动预热模型改为从 model_store 查 is_default=1
  - Settings API fallback 改为查 model_store
  - 运行时诊断函数适配
- `engine/async_engine.py`：新增 `set_startup_models()`，支持在 `lifespan()` 初始化 DB 后再注入预热模型
- `serve.py`：real-env 检查成功日志改为记录 preflight 返回的 model_id/provider，不再引用已删除字段
- `api/schemas.py`：未改动默认 model 字段（仍为 `trellis`，通过 server 侧兼容映射处理）
- `docker-compose.yml`：删除 `MODEL_PATH`、`MODEL_PROVIDER`、`MODEL_DIR` 卷挂载；添加 `HF_TOKEN`
- `docker/Dockerfile`：删除 `MODEL_PATH` 和 `MODEL_PROVIDER` ENV 行
- `.env.example`：同步清理

## Notes
- `build_model_runtime` 被 `ModelRegistry` 以 lazy 方式调用，此时 `model_store` 已 initialized
- mock 模式不需要 model_path，不受影响
- `provider_mode`（mock/real）保留在 config 中，这是部署模式而非模型配置
- 验证：
  - `.venv/bin/python -m pytest tests -q`（138 passed）
  - `cd web && npm run build`（通过）
