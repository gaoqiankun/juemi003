# Admin 面板布局规范统一
Date: 2026-03-23
Status: done
Commits: N/A（按 AGENTS.md，本轮不执行 commit）

## Goal
按设计规范统一 admin 全部页面的布局、间距、响应式行为。

## 设计规范

### 响应式
- 最小支持 iPad 横屏（1024px），不做任何小屏/移动端适配
- 侧边栏 + 内容区固定双列，不用 lg: 条件
- Header 固定横排，不用 xl: 条件
- 内容区撑满，不设 max-width
- 所有 md: 断点的列数改为默认值（768px 不会出现）

### 间距体系（3 级）
| 层级 | 用途 | 值 |
|------|------|-----|
| 页面级 | 卡片之间 | gap-4 = 16px |
| 卡片内 | 分组之间、字段网格 | gap-3 = 12px |
| 字段内 | label 到 input、按钮组 | gap-1.5 = 6px |

### 卡片
- padding 统一 p-4（16px）
- 圆角 rounded-lg（8px）

### 按钮
- Admin 操作按钮统一 size="sm"（h-8 = 32px）
- 不允许自定义 h-* 覆盖

## Key Decisions
- 仅调整布局/间距 class，不改任何业务逻辑、数据流和交互流程。
- Admin 统一按 1024px+ 桌面布局实现：移除 `md/lg/xl` 响应式分支，固定侧栏双列与 header 横排。
- 统一三层间距体系：页面级 `gap-4`、卡片内 `gap-3`、字段内 `gap-1.5`。
- 所有页面主卡片 padding 统一为 `p-4`，并移除按钮 `h-*` 自定义高度覆盖。

## Changes
- `web/src/components/layout/admin-shell.tsx`
  - 外层改为固定 `grid grid-cols-[280px_minmax(0,1fr)]`，去除 `lg:` 条件。
  - 侧栏改为固定 `sticky top-0 h-screen border-r`，去除移动端 `border-b` 退化样式。
  - Header 内层改为固定横排 `flex-row items-center justify-between px-6 py-4`。
  - Main 内容区改为 `flex w-full flex-col gap-4 px-6 py-4`，移除 `mx-auto` 与 `max-w-[1440px]`。
- `web/src/pages/tasks-page.tsx`
  - 页面级间距 `gap-6 -> gap-4`。
  - 统计卡网格改为固定 `grid-cols-4`（移除 `md/xl`）。
  - 卡片 `p-5 -> p-4`。
  - 任务列表卡片内分组 `gap-5 -> gap-3`，筛选头部固定横排（移除 `xl:`）。
- `web/src/pages/models-page.tsx`
  - 页面级间距 `gap-6 -> gap-4`，主卡片 `gap-5 p-5 -> gap-3 p-4`。
  - 字段内/分组间距对齐：`gap-2 -> gap-1.5`，`gap-2.5 -> gap-3`。
  - “设为默认”按钮移除 `h-7` 自定义高度，仅保留 `size=\"sm\"`。
- `web/src/pages/api-keys-page.tsx`
  - 页面级间距 `gap-6 -> gap-4`。
  - 双栏布局改为固定 `grid-cols-[minmax(0,1.5fr)_22rem]`（移除 `xl:`）。
  - 卡片 `p-5 -> p-4`，卡片内 `gap-5/gap-4 -> gap-3`。
  - 字段内按钮组/结果块间距统一为 `gap-1.5`。
- `web/src/pages/settings-page.tsx`
  - 页面级间距 `gap-6 -> gap-4`，卡片 `gap-4 p-5 -> gap-3 p-4`。
  - 字段网格固定 `grid-cols-3`，文本字段固定 `col-span-3`（移除 `md/xl`）。
  - HF 区域双列固定 `grid-cols-2`（移除 `md:`）。
  - 字段卡片内部 `gap-2 -> gap-1.5`，按钮区 `gap-3/gap-2 -> gap-1.5`。

## Notes
- 验证通过：
  - `cd web && npm run build`
  - `.venv/bin/python -m pytest tests -q`（138 passed）
