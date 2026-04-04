# Generate Page — Reference Image object-contain
Date: 2026-04-04
Status: done

## Goal
工作台参考图片预览用 object-cover，竖图/非正方形图片会被裁剪，用户看不到完整图片。

## Changes
`web/src/pages/generate-page.tsx:222`：
- `object-cover` → `object-contain`
- 容器背景可适当加深（已有 `bg-surface-container-lowest`），保持视觉一致

## Acceptance Criteria
1. `cd web && npm run build` 零错误
2. `cd web && npm run lint` 不新增问题
3. 竖图/横图均完整显示在 h-44 容器内，不裁剪
