# Light Theme 背景层级微调
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
收紧 light theme 的背景层级和卡片边界，让页面大背景、内嵌区块和白色卡片之间的关系更清晰，同时保持默认主题仍然是 dark。

## Key Decisions

- light theme 的 `surface` 系列变量按新的灰阶数值重设，不改 dark theme 主色盘
- 新增 `--outline-variant`，并让现有 `--ghost-outline` 对齐到该变量，避免边框语义继续漂移
- `Card` 组件补 `data-card` 标记，让 light theme 能精确挂载超轻阴影，不影响其它非卡片容器
- `use-theme.tsx` 保持“无 localStorage 时默认 dark”，不再跟随系统偏好

## Changes

- `web/src/styles/tokens.css`
  - light theme 背景层级变量调整为新的 `surface` / `surface-container-*`
  - light theme 新增 `--outline-variant: #E2E2E5`
  - light theme 的 `.card` / `[data-card]` 加入 `0 1px 3px rgba(0,0,0,0.05)` 轻阴影
- `web/src/components/ui/card.tsx`
  - 为统一卡片挂上 `data-card`
- `web/src/hooks/use-theme.tsx`
  - 默认主题仍为 `dark`，本次只复核未再改动

## Notes

- 构建验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
- light theme 对比截图：
  - `output/playwright/light-theme-compare/setup-before.png`
  - `output/playwright/light-theme-compare/setup-after.png`
