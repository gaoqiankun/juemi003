# Generate Viewer Theme Stability
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
排查并修复 `generate-page.tsx` 中间 3D 视口在切换主题时的布局错乱问题，确保主题切换只更新颜色，不重建 viewer，也不触发额外的模型请求或明显 layout shift。

## Key Decisions

- `ThreeViewer` 改为只在挂载时创建一次 `Viewer3D` 实例
- 主题切换涉及的背景色和网格色改为通过实例方法更新，而不是通过 React effect 销毁并重建 viewer
- `generate-page.tsx` 里基于 `getComputedStyle` 读取 token 的逻辑保留；它本身只是纯读取，没有副作用，真正的问题是读取结果被绑定到了 viewer 创建 effect
- 中间列容器不改尺寸结构；布局抖动来自 viewer 重建，而不是 generate 页卡片尺寸样式

## Changes

- `web/src/components/three-viewer.tsx`
  - viewer 创建 effect 改为仅在首次挂载执行
  - 新增背景色同步 effect：`setBackground(background)`
  - 新增网格色同步 effect：`setGridColors(gridPrimaryColor, gridSecondaryColor)`
- `web/src/lib/viewer.ts`
  - 新增 `setBackground()`，只更新场景背景并重绘
  - 新增 `setGridColors()`，重建 grid helper 但保留现有 viewer、camera、controls 和 model，不触发整实例重建

## Notes

- 构建验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
- Playwright 验收：在 `/generate` 的 completed 视口状态下切换主题，服务端未出现新的 `GET /v1/tasks/{id}/artifacts/model.glb`，说明主题切换没有触发 viewer 重建
- 验收截图：
  - `output/playwright/generate-theme-stability/generate-before-toggle.png`
  - `output/playwright/generate-theme-stability/generate-after-toggle.png`
