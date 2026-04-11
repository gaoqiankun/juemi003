# 默认主题改为暗色
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
调整前端主题初始化逻辑，让应用在 localStorage 没有主题记录时默认使用暗色，而不是跟随系统 `prefers-color-scheme`。

## Key Decisions

- 保留已有的优先级：`document.documentElement.dataset.theme` 优先，其次是 localStorage
- 仅移除系统主题探测分支，不改主题切换、持久化和运行时同步逻辑

## Changes

- `web/src/hooks/use-theme.tsx`
  - 删除 `prefers-color-scheme: light` 分支
  - 无本地值时统一回落到 `dark`

## Notes

- 构建验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
