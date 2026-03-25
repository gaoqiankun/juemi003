# 模型列表操作列回归单列与槽位用量拆分
Date / Status: 2026-03-23 / done / Commits: N/A（按 AGENTS.md，本轮不执行 commit）

## Goal
修复 Admin 模型列表两项 UI/数据问题：  
1) 操作列从多列回归单列，三个操作按钮始终可见并通过 disabled 表达状态。  
2) 运行状态列仅保留 Badge/错误信息，新增独立「槽位用量」列展示 `tasks_processed / max_tasks_per_slot`。

## Key Decisions
- 操作区保持单个 `<td>`，内部用 `flex items-center gap-2` 保障三行视觉一致且无占位空白。
- 加载按钮统一始终渲染：`ready/loading` 禁用，`not_loaded/error` 可点击；按钮文案由 `runtime_state` 决定。
- 槽位用量按产品要求只在 `runtime_state=ready` 时显示，其他状态显示 `—`。
- `max_tasks_per_slot` 直接由后端 `/api/admin/models` 响应下发（同时提供 snake_case 与 camelCase 兼容前端解析）。

## Changes
- `/Users/gqk/work/hey3d/gen3d/web/src/pages/models-page.tsx`
  - 表头操作列去掉 `colSpan`，恢复为单列；新增「槽位用量」列（位于运行状态右侧）。
  - `tbody` 操作区合并回单个 `<td>`，按钮顺序改为：启用开关 → 设为默认 → 加载/重试。
  - 移除运行状态列中的「已处理」文案，仅保留 Badge 与错误信息。
  - 加载按钮始终显示并按状态映射文案/禁用态：已加载、加载中、加载、重试。
  - 空状态 `colSpan` 调整为 4（与当前列数一致）。
- `/Users/gqk/work/hey3d/gen3d/web/src/hooks/use-models-data.ts`
  - `AdminModelItem` 新增 `maxTasksPerSlot`，并从模型列表响应解析 `max_tasks_per_slot/maxTasksPerSlot`。
- `/Users/gqk/work/hey3d/gen3d/web/src/lib/admin-api.ts`
  - `RawAdminModelRecord` 新增 `max_tasks_per_slot` 与 `maxTasksPerSlot` 字段声明。
- `/Users/gqk/work/hey3d/gen3d/api/server.py`
  - `GET /api/admin/models` 为每个模型追加 `max_tasks_per_slot` 与 `maxTasksPerSlot`（值来自 `model_scheduler.max_tasks_per_slot`）。
- `/Users/gqk/work/hey3d/gen3d/api/schemas.py`
  - `AdminModelDetail` 新增 `max_tasks_per_slot` 字段。
- `/Users/gqk/work/hey3d/gen3d/web/src/i18n/en.json`
  - 新增 `models.list.columns.slotUsage = "Slot Usage"`。
  - 新增 `models.list.loaded = "Loaded"`，并将 `models.list.loading` 调整为 `"Loading"`。
- `/Users/gqk/work/hey3d/gen3d/web/src/i18n/zh-CN.json`
  - 新增 `models.list.columns.slotUsage = "槽位用量"`。
  - 新增 `models.list.loaded = "已加载"`，并将 `models.list.loading` 调整为 `"加载中"`。
- `/Users/gqk/work/hey3d/gen3d/tests/test_api.py`
  - 在 admin models 测试中补充 `maxTasksPerSlot/max_tasks_per_slot` 字段一致性与类型断言。

## Notes
- 验证通过：
  - `cd /Users/gqk/work/hey3d/gen3d && ./.venv/bin/python -m pytest tests/test_api.py -k "admin_model_load_endpoint_returns_runtime_state or admin_models_returns_friendly_error_message_when_runtime_load_fails" -q`
  - `cd /Users/gqk/work/hey3d/gen3d/web && export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" && npm run build`
- 命令输出中存在本地环境提示：`pyenv: cannot rehash ... isn't writable`，不影响测试与构建结果。
