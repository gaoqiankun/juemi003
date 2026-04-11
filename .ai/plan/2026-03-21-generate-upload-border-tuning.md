# Generate 上传区虚线边框增强
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
让 `generate-page.tsx` 的上传区域在亮色和暗色主题下都始终显示可见的虚线边框，hover 时只用 accent 色做交互反馈。

## Key Decisions

- 不改上传、拖拽、预览或清除逻辑，只调整上传区容器的边框表现
- 将常驻虚线边框从 `border` 提升到 `border-2`，提升两套主题下的可见度
- 保留现有 hover 反馈，但边框颜色只在 hover 时切到 accent

## Changes

- `web/src/pages/generate-page.tsx`
  - 上传容器改为 `border-2 border-dashed border-outline`
  - hover 继续使用 `border-accent`

## Notes

- 构建验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
