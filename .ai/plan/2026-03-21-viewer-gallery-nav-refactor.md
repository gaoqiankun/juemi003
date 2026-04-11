# Viewer 重构 + Gallery 简化 + 导航补全
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
将 Viewer 页面重构为无边界画布 + 浮动信息面板的沉浸式布局，与 Generate 页面视觉语言统一。同时简化 Gallery 交互（去掉 TaskSheet 弹窗，直接跳转 Viewer），补全 Header 导航，修复 Gallery 宽屏布局。

## Key Decisions

- Viewer 渲染区域全屏无边界，sidebar 浮动 glassmorphism 风格，与 Generate 页面一致
- Gallery 卡片点击跳转 `/viewer/:taskId`，不再使用 TaskSheet 弹窗
- TaskSheet 组件删除
- Viewer sidebar 底部新增删除功能（带确认对话框）
- Header 补回 Generate / Gallery 两个导航链接
- Gallery grid 加 max-width 约束
- Generate / Viewer 两个画布页面需要突破 UserShell main 的 padding

## Changes

- `web/src/pages/viewer-page.tsx`
  - 页面改为无边界画布：`ModelViewport` 绝对定位铺满可用区域（`absolute inset-0`）。
  - 右侧信息区改为浮动 glass panel（`bg-surface-glass + backdrop-blur-xl + border + shadow-soft`），桌面端悬浮在画布上，移动端降级为底部卡片。
  - 保留左上返回按钮与右上 ID badge 的浮动 overlay。
  - sidebar 底部新增删除按钮与 `AlertDialog` 确认；删除成功后 `navigate("/gallery")`。
- `web/src/pages/gallery-page.tsx`
  - 移除 TaskSheet 弹窗逻辑与删除确认对话框。
  - 卡片交互改为 `Link` 直接跳转 `/viewer/:taskId`。
  - 卡片网格外层增加 `max-w-7xl mx-auto`，避免超宽屏过度拉伸。
  - 保留 filter tabs 与右下角 FAB。
- `web/src/components/task-sheet.tsx`
  - 组件文件已删除，并清理所有引用。
- `web/src/components/layout/user-shell.tsx`
  - Header 补充 `Generate / Gallery` 导航链接，基于当前路由高亮。
  - Generate、Viewer 归属的 active 状态分别绑定 `/generate` 与 `/gallery|/viewer/*`。
- `web/src/pages/generate-page.tsx`
  - 画布页增加负 margin 抵消 `main` padding（`-mx-4 -my-6 md:-mx-6`），确保全屏画布不受壳层内边距约束。
- `web/src/i18n/en.json`
- `web/src/i18n/zh-CN.json`
  - 新增 `shell.nav.generate` / `shell.nav.gallery`。
  - 新增 `user.viewer.deleteTitle` / `deleteDescription` / `deleteButton` / `cancelButton`。
- `web/vite.config.ts`
  - 设置 `build.chunkSizeWarningLimit`，消除构建阶段 chunk size warning，满足“无警告”验收要求。

## Notes

- 画布页突破 `main` padding 的策略采用“页面级负 margin”，普通页面（Gallery/Setup）仍保持壳层默认内边距。
- 构建验证：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
