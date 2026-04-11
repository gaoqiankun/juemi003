# Settings 页 max_loaded_models 校验交互修复
Date: 2026-03-24
Status: done

Date / Status: 2026-03-24 / done / Commits: N/A（按 AGENTS.md，本轮不执行 commit）
## Goal
- 在设置页补齐 `sonner` 全局挂载，并调整 `max_loaded_models` 的错误反馈与校验状态行为：
  - 非法值保存时改为 `toast.error(...)`
  - 移除保存按钮旁的 inline 错误文案
  - 值改回合法后立即清除校验错误状态并恢复保存按钮可用

## Key Decisions
- 在应用根节点新增 `<Toaster />`，统一承载现有/新增 toast 消息。
- `maxLoadedModels` 使用前端校验函数复用后端同语义文案（`must be an integer` / `between 1 and N`）。
- 仅在点击保存并命中非法值后进入 `maxLoadedModelsError` 状态；该状态存在时禁用保存按钮。
- 输入变化后自动重新校验，合法即清空 `maxLoadedModelsError`，避免按钮卡死。

## Changes
- `/Users/gqk/work/hey3d/gen3d/web/src/main.tsx`
  - 引入并挂载 `sonner` 的 `<Toaster />` 到应用根节点。
- `/Users/gqk/work/hey3d/gen3d/web/src/pages/settings-page.tsx`
  - 新增 `maxLoadedModels` 校验辅助函数（字段定位、上限解析、合法性校验）。
  - 保存时若 `maxLoadedModels` 非法，触发 `toast.error(...)` 并写入 `maxLoadedModelsError`。
  - 捕获后端错误时改为 toast 提示；若错误属于 `maxLoadedModels`，保持错误状态用于禁用保存按钮。
  - 新增输入变更后重校验逻辑：当值合法时立即清空 `maxLoadedModelsError`。
  - 保存按钮禁用条件增加 `Boolean(maxLoadedModelsError)`。
  - 删除保存按钮旁的 inline 错误文本展示。

## Notes
- 验证通过：
  - `cd /Users/gqk/work/hey3d/gen3d/web && export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" && npm run build`
