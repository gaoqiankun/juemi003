# 用户侧模型选择：GET /v1/models + 前端动态下拉
Date: 2026-03-22
Status: done
Commits: N/A（按仓库 AGENTS 约束，本次未执行 git commit）

## Goal
用户在 Generate 页可以看到后端 enabled 的模型列表并选择，提交任务时带上 model_id。

## Key Decisions
- 新端点 `GET /v1/models`，复用 `require_api_key` 认证
- 只返回 `is_enabled=True` 的模型，字段精简（id, display_name, is_default）
- 前端从后端动态拉取，不再硬编码
- 提交任务时带 model_id
- 本轮不改 engine 路由逻辑（多模型运行时后续再做）

## Changes
- `api/server.py`: 新增 `GET /v1/models`（Bearer 鉴权），数据来自 `ModelStore.get_enabled_models()`，仅返回 `id/display_name/is_default`
- `api/server.py`: 放宽 `build_model_runtime()` 的模型名校验，允许任务记录使用 `trellis2` 这类 model id，同时仍走现有全局 Provider（未改 engine 路由策略）
- `api/schemas.py`: 新增 `UserModelSummary`、`UserModelListResponse` 响应模型
- `web/src/lib/api.ts` + `web/src/lib/types.ts`: 新增用户模型列表请求与类型，`TaskCreatePayload` 增加 `model` 字段
- `web/src/pages/generate-page.tsx`: Generate 页启动时拉取 `/v1/models`，动态渲染下拉；默认选择 `is_default=true`；增加加载/失败/空列表/未配置 token fallback 状态
- `web/src/app/gen3d-provider.tsx`: `submitNewTask()` 构建 `TaskCreatePayload` 时带上 `model`；`submitCurrentFile()`/`retryCurrentTask()` 接收并传递所选 model id
- `web/src/i18n/en.json`、`web/src/i18n/zh-CN.json`: 增加模型下拉 fallback 文案
- `tests/test_api.py`: 新增 `test_list_models_requires_auth`、`test_list_models_returns_enabled`
- `tests/test_api.py`: 新增 `test_create_task_persists_selected_model_id`，验证 task 记录中的 `model` 与提交值一致

## Notes
- engine 层暂不改，后端收到 model_id 先存到 task 记录里，实际执行仍用全局 Provider
- 后续多模型运行时改造时，engine 根据 task 的 model_id 路由到对应 Provider
- 验证：
  - `.venv/bin/python -m pytest tests -q` → `128 passed`
  - `cd web && npm run build`（Node v24.14.0）→ 通过，TypeScript 无报错
