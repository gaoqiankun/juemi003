# 用户模型库路由恢复
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
恢复用户侧原有的 `/gallery` 模型库页面，撤回误引入的 `generations-page.tsx`，并把用户导航与回链统一指回模型库。

## Key Decisions

- 按指定 commit `0b6f1f2` 取回 `web/src/pages/gallery-page.tsx`，不重新发明页面逻辑
- `user-shell.tsx` 恢复成极简 header：左侧只保留 Logo + `Cubie 3D`，右侧只保留连接状态点、主题切换、语言切换、设置齿轮
- `/gallery` 重新作为用户模型库主路由，彻底删除错误的 `/generations` 用户入口
- `gallery-page.tsx` 只做视觉迁移：改用 `tokens.css` / 语义色 token，不改筛选、选中、TaskSheet、删除确认等功能逻辑
- Generate 页“查看全部”和 Viewer 页返回按钮都改回模型库链路

## Changes

- `web/src/pages/gallery-page.tsx`
  - 从 commit `0b6f1f2` 恢复原页面
  - 将黑白硬编码色值迁移为 token 驱动的 grid / card / hover / dialog 样式
  - 新增 `react-i18next` 文案接入，保留原有筛选和交互逻辑
- `web/src/App.tsx`
  - 新增 `/gallery -> GalleryPage`
  - 删除 `/generations` 用户路由
- `web/src/components/layout/user-shell.tsx`
  - 去掉 header 内全部导航 tab
  - 恢复 AppShell 风格的极简头部结构
  - 连接状态点直接读取 `useGen3d().connection`
- `web/src/pages/generate-page.tsx`
  - “查看全部”链接改回 `/gallery`
- `web/src/pages/viewer-page.tsx`
  - 返回按钮改回 `/gallery`
- `web/src/i18n/en.json` / `web/src/i18n/zh-CN.json`
  - 新增 `user.shell.nav.gallery`
  - 新增 `user.gallery.*` 文案
  - `user.viewer.backButton` 改为返回模型库
- 删除 `web/src/pages/generations-page.tsx`

## Notes

- 验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
- 当前 `/gallery` 仍受 `ProtectedUserRoute` 保护；是否展示真实模型网格取决于当前 API 配置和任务列表返回结果
