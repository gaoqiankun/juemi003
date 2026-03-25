# Gallery Token 样式迁移补齐
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
补齐用户模型库页面的 token 样式迁移，只替换 gallery 相关视觉表现中的硬编码颜色，不改任何任务列表、筛选、删除、TaskSheet 或 AlertDialog 的功能逻辑。

## Key Decisions

- `web/src/pages/gallery-page.tsx` 保持原布局与交互，只调整筛选 active 态、空状态和“加载更多”按钮的颜色语义
- gallery 链路中的弹层组件一起收口：`TaskSheet`、`TaskStatusBadge`、`AlertDialog` 的黑白硬编码全部改成 `tokens.css` / Tailwind token
- 3D viewer 的背景色不再写死，改为运行时读取 `--surface-container-lowest`
- 亮色 / 暗色主题验收通过本地预览页截图完成，不改源码路由

## Changes

- `web/src/pages/gallery-page.tsx`
  - 筛选栏 active 状态改为 accent 语义色
  - 空状态卡片改成 token 渐变背景
  - “加载更多”按钮 hover 态改成 accent + surface token
- `web/src/components/task-sheet.tsx`
  - overlay、关闭按钮、左右面板、主 CTA、删除按钮迁移到 token 体系
  - viewer 背景改为读取 CSS token，不再写死深色 hex
- `web/src/components/task-status-badge.tsx`
  - 成功 / 失败 / 处理中状态统一改为 success / danger / warning token
  - 进度文案改为 `text-muted`
- `web/src/components/ui/alert-dialog.tsx`
  - overlay 改为基于 `--surface` 的半透明遮罩

## Notes

- 构建验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
- 亮暗主题截图：
  - `output/playwright/gallery-theme-check/gallery-dark.png`
  - `output/playwright/gallery-theme-check/gallery-light.png`
