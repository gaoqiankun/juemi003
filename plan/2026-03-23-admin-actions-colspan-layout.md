# Admin 操作列表格列对齐修复
Date / Status: 2026-03-23 / planning→done / Commits: N/A（按 AGENTS.md，本轮不执行 commit）

## Goal
修复 Admin 的模型列表与 API Key 列表中“操作”列的按钮尺寸和列对齐问题：按钮回退为 `size="sm"`，并将操作区改为多列 `<td>` 结构，确保跨行垂直对齐。

## Key Decisions
- 不改任何 i18n key 与业务逻辑，仅调整表格结构和样式 class。
- 通过 `thead` 的 `colSpan` 把“操作”表头跨到多个子列，保持水平居中。
- `tbody` 中每个操作都用固定宽度独立 `<td>`，条件操作改为“td 始终存在、内容条件渲染”。

## Changes
- `/Users/gqk/work/hey3d/gen3d/web/src/pages/models-page.tsx`
  - 操作区从单个 `<td>` 拆为 3 个独立 `<td>`（Load/Retry/Loading、Enable/Disable、Set Default）。
  - 表头 `models.list.columns.actions` 增加 `colSpan={3}`，空状态 `colSpan` 从 3 调整为 5。
  - 为三列操作 `<td>` 设置固定宽度（160/200/160），按钮 `size` 从 `xs` 回退到 `sm`。
  - Load/Retry/Loading 操作改为保留 `<td>`，仅按钮内容按 runtime_state 条件渲染。
- `/Users/gqk/work/hey3d/gen3d/web/src/pages/api-keys-page.tsx`
  - 操作区从单个 `<td>` 拆为 2 个独立 `<td>`（Enable/Disable、Delete）。
  - 表头 `apiKeys.table.columns.actions` 增加 `colSpan={2}`，空状态 `colSpan` 从 4 调整为 5。
  - 两个操作 `<td>` 固定宽度（132/112），相关按钮 `size` 从 `xs` 回退到 `sm`。

## Notes
- 验证：`cd /Users/gqk/work/hey3d/gen3d/web && npm run build` 通过。
- 结果满足本轮验收点：按钮 size 统一为 `sm`、操作表头使用 `colSpan`、每行操作 `<td>` 独立并可按列对齐。
