# Admin 面板 Bug 修复 + 全站标题清理 + Dashboard 精简
Date: 2026-03-22
Status: done
Commits: N/A（按仓库 AGENTS 约束，本次未执行 git commit）

## Goal
修复部署测试中发现的 Admin 面板功能 bug、全站标题层级冗余问题、Dashboard 去除不属于应用层的硬件监控信息。

## Key Decisions
- Admin 端统一走 `require_admin_token`（`/api/admin/tasks` 与 `/api/admin/keys` 不再使用 privileged scope token）。
- 在 Admin Shell 层实现 token guard：无 token 或 401 时先展示 token 输入，不再让各页直接报错。
- 模型页通过前端映射适配 `/api/admin/models` 原始数据结构，同时对时间格式化增加空值/非法值防御，避免 `RangeError: Invalid time value`。
- 标题清理采用统一规则：页面主标题保留一级，去除与主标题重复的分类小字。
- Dashboard 仅保留业务指标（统计卡片 + 最近任务），去除 GPU/节点硬件监控展示。

## Changes
- `api/server.py`
  - `/api/admin/tasks`、`/api/admin/keys`（GET/POST/PATCH）改为 `Depends(require_admin_token)`。
- `tests/test_api.py`
  - 同步更新 admin keys/tasks 认证路径与断言（含 migration 相关用例）。
- `web/src/lib/admin-api.ts`
  - 新增 `clearAdminToken()`、`verifyAdminToken()`、`AdminApiError`；
  - `adminFetch()` 在 401 时清理 token 并派发 `cubie-admin-auth-invalid` 事件。
- `web/src/components/layout/admin-shell.tsx`
  - 新增 token 输入与校验界面（Admin auth guard）；
  - Sidebar 品牌区仅保留 logo + `Cubie`，移除上方小字；
  - 顶栏移除“工作区/Workspace”小字，仅保留页面标题。
- `web/src/hooks/use-models-data.ts`
  - 将 `/api/admin/models` 的原始结构映射为前端 `ModelsData`，稳定渲染模型页。
- `web/src/lib/admin-format.ts`
  - `formatTimestamp()` 增加空值/非法时间防御（返回 `—`）。
- `web/src/i18n/en.json`、`web/src/i18n/zh-CN.json`
  - 补全 `settings.fields.queueMaxSize.*`、`settings.fields.rateLimitPerHour.*`、`settings.fields.rateLimitConcurrent.*`；
  - 新增 `shell.adminAuth.*` 文案。
- 页面标题层级清理
  - `web/src/pages/dashboard-page.tsx`：移除顶部重复小字；删除 GPU 卡片与节点硬件监控区，仅保留业务统计 + 最近任务。
  - `web/src/pages/settings-page.tsx`：移除页面顶部“设置”小字。
  - `web/src/pages/tasks-page.tsx`、`web/src/pages/models-page.tsx`、`web/src/pages/api-keys-page.tsx`：移除页面顶部重复分类小字。
  - `web/src/pages/setup-page.tsx`：移除“连接设置”小字。

## Notes
- 验证结果：
  - `.venv/bin/python -m pytest tests -q` → `128 passed`
  - `cd web && npm run build`（Node v24.14.0）→ 通过，TypeScript 无错误
- 本轮未修改 engine 层、ModelStore/SettingsStore 存储层，以及用户侧 Generate/Gallery/Viewer 页面。
