# API Keys 状态列与操作列布局调整
Date: 2026-03-24
Status: done

Date / Status: 2026-03-24 / done / Commits: N/A（按 AGENTS.md，本轮不执行 commit）
## Goal
按要求调整 `api-keys` 列表：状态列去掉圆点指示器，操作列由两列 `<td>` 合并为单列，并保持按钮紧凑排列。

## Key Decisions
- 状态列采用 `Badge`（与模型列表风格一致），不再使用带圆点的 `StatusDot`。
- 操作按钮合并到一个单元格，通过 `flex items-center justify-center gap-2` 控制紧凑水平布局。

## Changes
- `/Users/gqk/work/hey3d/gen3d/web/src/pages/api-keys-page.tsx`
  - `StatusDot` 替换为 `Badge`，状态列不再显示圆点。
  - 表头 `actions` 去掉 `colSpan`。
  - `<colgroup>` 从 5 列调整为 4 列，操作列宽度改为单列。
  - `tbody` 操作区从两个独立 `<td>`（启停/删除）合并为一个 `<td>`。
  - 空状态行 `colSpan` 从 `5` 调整为 `4`。

## Notes
- 验证通过：
  - `cd /Users/gqk/work/hey3d/gen3d/web && export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" && npm run build`
- 构建输出中的 `pyenv: cannot rehash ...` 为本地环境提示，不影响编译成功。
