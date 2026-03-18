# 启动预热与 /health UI 对齐
Date / Status: 2026-03-18 / done / Commits: uncommitted

## Goal
- 服务启动后自动后台预热默认模型，不再依赖首个任务触发加载
- 保持 `/ready` 语义不变：模型 ready 后才返回 200
- Web UI 右上角连接状态改为基于 `/health`，并确保任务提交不依赖 `/ready`

## Key Decisions
- `engine.start()` 结束前只调度模型预热，不等待模型加载完成，避免阻塞 FastAPI 启动
- 预热模型列表先固定为当前唯一支持的 `trellis`，通过 `AsyncGen3DEngine(startup_models=...)` 传入
- Web UI 的连接绿点与设置页“测试连接”统一改为 `/health`，`/ready` 继续保留给运维探针

## Changes
- `engine/async_engine.py`：新增 `startup_models` 参数，启动后立即调度 `ModelRegistry.load(...)`
- `api/server.py`：创建引擎时传入默认预热模型 `("trellis",)`
- `static/router.js`：`pingReady()` 改为 `pingHealth()`，连接状态取 `/health`
- `static/settings.js` / `static/generate.js` / `static/index.html`：更新 `/health` 文案，去掉等待 `/ready` 才可提交流程的提示
- `tests/test_api.py`：更新 readiness 相关测试，覆盖“启动即异步预热且不阻塞”“预热期间任务仍可创建”

## Notes
- `/health` 仍然只表示进程存活；`/readiness` 与 `/ready` 仍然只在模型 ready 后返回 200
- 本地回归：`python -m pytest tests -q` 结果为 `69 passed`
