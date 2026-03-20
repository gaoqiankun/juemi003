# Header 与冗余文案清理
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
清理 user/admin shell header 右侧的文字标签，让主题切换、语言切换都只保留图标；同时移除非 Setup 页面里明显冗余的说明型副文案，并给 icon-only 按钮补齐可访问性标签。

## Key Decisions

- user-shell 与 admin-shell 的 header 右侧统一成“连接状态点 + 主题图标 + 语言图标 + 设置图标”
- 主题和语言切换都只保留图标；语言按钮通过 `title` 暴露当前语言，主题按钮通过 `title` 暴露当前主题
- Setup 页保留说明文字，其余页面只清理明显的页面级副标题、占位说明与 shell 占位 copy，不改核心功能文案
- 所有 icon-only 按钮必须保留 `aria-label`

## Changes

- `web/src/components/layout/user-shell.tsx`
  - 主题切换改为纯图标按钮
  - 语言切换改为纯图标按钮，tooltip 显示当前语言
  - 去掉主题/语言按钮外层 wrapper 的背景和边框，按钮默认透明，仅 hover 显示底色
- `web/src/components/layout/admin-shell.tsx`
  - 顶部右侧 controls 改成与 user-shell 一致
  - 去掉主题/语言文字标签与环境按钮
  - 去掉 shell 内部品牌 copy 和 deploy copy
  - 去掉主题/语言按钮共同 wrapper 的背景和边框，按钮默认透明，仅 hover 显示底色
- `web/src/pages/dashboard-page.tsx`
  - 移除页面顶部描述和 GPU 卡片副说明
- `web/src/pages/tasks-page.tsx`
  - 移除页面顶部描述
- `web/src/pages/models-page.tsx`
  - 移除页面顶部描述和 import 卡片副说明
- `web/src/pages/api-keys-page.tsx`
  - 移除页面顶部描述
- `web/src/pages/settings-page.tsx`
  - 移除页面顶部描述
- `web/src/pages/generate-page.tsx`
  - 上传区清除按钮补 `aria-label`
- `web/src/components/task-sheet.tsx`
  - 关闭按钮补 `aria-label`

## Notes

- 构建验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
- 截图验收：
  - `output/playwright/header-cleanup/user-header.png`
  - `output/playwright/header-cleanup/admin-header.png`
