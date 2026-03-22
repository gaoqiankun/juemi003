# Admin 面板第五轮打磨：模型/密钥操作完善 + Settings 精简 + 语言切换
Date: 2026-03-22
Status: done
Commits: N/A（按仓库 AGENTS 约束，本次未执行 git commit）

## Goal
9 个问题的集中修复：模型页操作精简、密钥页功能补全、Settings 布局精简、i18n 修正、语言切换一致性。

## Key Decisions
- 模型不允许运行时删除，只保留启用/禁用 + 设为默认
- 密钥页新增停用/启用 + 删除操作，需后端补接口
- Settings 去掉字段描述文字，只保留字段名 + 输入控件
- Admin 语言切换改为下拉菜单（与用户侧行为一致）
- 模型状态调研结论：后端已有运行时状态能力，`GET /api/admin/models` 会附带 `runtimeState`（来自 `ModelRegistry.get_state`，典型值：`ready` / `loading` / `not_loaded` / `error`，异常时兜底 `unknown`），因此前端显示真实运行时状态标签，而不是仅凭配置开关推断。

## Changes
- 模型页（移除删除、去掉冗余 ID、显示真实状态）
  - `web/src/pages/models-page.tsx`
    - 删除按钮与删除逻辑移除；
    - 模型名列仅保留 `displayName`，去掉小字 `id`；
    - 状态列显示两类只读标签：运行时状态（`runtimeState`）+ 启用配置（已启用/已禁用）；
    - 操作列仅保留启用/禁用开关与“设为默认”按钮。
  - `web/src/hooks/use-models-data.ts`
    - 移除 `removeModel`；
    - 增加 `runtimeState` 解析与标准化。
  - `web/src/lib/admin-api.ts`
    - 移除前端 `deleteModel` 调用导出，模型侧不再暴露删除操作。
- 密钥页（去掉 key_id 列、补停用/启用与删除）
  - 后端：
    - `storage/api_key_store.py`：新增 `revoke_user_key(key_id)`（仅删除 `scope=user`）。
    - `api/server.py`：新增 `DELETE /api/admin/keys/{key_id}`，调用 `revoke_user_key`，不存在返回 404。
    - 既有 `PATCH /api/admin/keys/{key_id}` 继续用于启用/停用（`isActive`）。
  - 前端：
    - `web/src/lib/admin-api.ts`：新增 `setAdminKeyActive()`、`deleteAdminKey()`。
    - `web/src/hooks/use-api-keys-data.ts`：新增 `setKeyActive()`、`removeKey()` 与 `busyKeyId`。
    - `web/src/pages/api-keys-page.tsx`：
      - 表格去掉 key_id/token 列，改为 名称 / 创建时间 / 状态 / 操作；
      - 操作列新增「启用/停用」和「删除（确认弹窗）」；
      - 操作后刷新列表，状态立即更新。
- Settings 页面精简
  - `web/src/pages/settings-page.tsx`：移除字段描述段落 `<p>{t(field.descriptionKey)}</p>`，仅保留 label + 输入控件。
- Dashboard / Tasks 列标题修正
  - `web/src/i18n/en.json`、`web/src/i18n/zh-CN.json`
    - `dashboard.recentTasks.columns.owner` 与 `tasks.table.columns.owner` 均改为 `"API Key"`。
- Admin 语言切换改为下拉菜单
  - `web/src/components/layout/admin-shell.tsx`
    - 地球图标改为弹出语言菜单（English / 简体中文）；
    - 支持外部点击关闭、Esc 关闭，行为与用户侧一致。
- i18n 同步
  - `web/src/i18n/en.json`、`web/src/i18n/zh-CN.json`
    - 新增模型运行时状态文案（ready/loading/not_loaded/error/unknown）；
    - 新增密钥操作文案（enable/delete/saving/confirmDelete）与操作列表头。
- 测试
  - `tests/test_api.py`
    - 在 admin key CRUD 流程测试中补充删除用例断言：删除后列表消失、删除不存在 key 返回 404。

## Notes
- 验证结果：
  - `.venv/bin/python -m pytest tests -q` → `130 passed`
  - `cd web && npm run build`（Node v24.14.0）→ 通过，TypeScript 无错误
