# Gallery History Header 对齐
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
参考 `design/user-dark.html` 的 `HistoryScreen`，调整 `web/src/pages/gallery-page.tsx` 的页头与筛选条样式，并补上跳转到生成页的 FAB，不改模型卡片、任务列表、TaskSheet 或删除逻辑。

## Key Decisions

- 只改 gallery 页头和筛选条视觉，卡片 DOM 与交互保持原状
- 筛选条改为 segmented control pill，去掉原先的图标筛选项，保留原筛选逻辑和状态值
- 页头只保留主标题，不保留 eyebrow 小字提示
- FAB aria 文案继续走 `i18n`
- FAB 固定在右下角，直接跳 `/generate`

## Changes

- `web/src/pages/gallery-page.tsx`
  - 新增页头：只保留 h1 `生成历史`
  - 筛选条改为 `inline-flex` pill segmented control，active/hover 状态按 token 语义色重做
  - 页面底部新增固定定位 FAB，点击跳到 `/generate`
- `web/src/i18n/en.json`
- `web/src/i18n/zh-CN.json`
  - 补充 `user.gallery.title`、`user.gallery.create`

## Notes

- 构建验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
- 亮暗主题截图：
  - `output/playwright/gallery-history-screen/gallery-light.png`
  - `output/playwright/gallery-history-screen/gallery-dark.png`
