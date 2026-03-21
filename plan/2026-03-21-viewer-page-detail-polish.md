# Viewer 页面细节打磨
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
- 优化 Viewer sidebar 信息密度与可读性：标题语义、输入图可见性、操作按钮简化、时间展示长度、圆角统一。

## Key Decisions
- 标题直接显示短 Task ID（`XXXXXXXX`），去掉重复 code badge。
- 参考图优先使用 `task.previewDataUrl`，仅在存在时展示。
- 删除 Share Link 入口，保持下载 + 删除为主操作。
- `MODIFIED` 使用 `formatRelativeTime`（按当前语言）避免小卡片溢出。
- sidebar 面板圆角统一为 `rounded-2xl`，与生成页风格一致。

## Changes
- `web/src/pages/viewer-page.tsx`
  - 标题改为 `shortTaskId`。
  - 移除标题下的 Task ID code badge，仅保留状态 badge。
  - 在标题区和 stat grid 之间新增参考图预览（存在 `task.previewDataUrl` 时渲染）。
  - 删除 Share 按钮与相关 clipboard/toast 逻辑，清理 `Share2` import。
  - `updatedLabel` 改为 `formatRelativeTime(task.updatedAt || task.createdAt, i18n.resolvedLanguage)`。
  - sidebar 外层圆角改为 `rounded-2xl`。

## Notes
- 构建验证通过：
  - `cd web && PATH=\"$HOME/.nvm/versions/node/v24.14.0/bin:$PATH\" npm run build`
