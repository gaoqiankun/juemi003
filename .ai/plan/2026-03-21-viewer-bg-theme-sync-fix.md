# Viewer 背景色主题同步 + 径向渐变修复
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done
## Goal
1. 修复切换 dark/light 主题时 3D viewer 背景色不跟随更新的 bug
2. 将 viewer 背景从纯色改为径向渐变（中心稍亮、边缘更暗），对齐商业平台（Tripo/Meshy/HunYuan3D）的查看体验

## Root Cause (Bug)
`GeneratePage` 在 render 阶段用 `getComputedStyle` 读 CSS variable，但 `ThemeProvider` 的 `useEffect` 要到 commit 后才写 `data-theme` 到 DOM → 读到旧值 → prop 不变 → `setBackground()` 不触发。

## Key Decisions
- 不再用 `getComputedStyle` 读 viewer 颜色，改为 `useViewerColors()` hook 直接映射常量
- viewer 背景改为径向渐变：`Viewer3D` 用 canvas 2D 绘制 512x512 径向渐变纹理作为 `scene.background`
- `setBackground()` 改为接收双色参数 `(centerColor, edgeColor)`
- 缩略图渲染器 `renderModelThumbnail` 保持纯色，不受影响

## Changes
- **新增** `web/src/hooks/use-viewer-colors.ts`：theme → `backgroundCenter` / `backgroundEdge` / grid / text 颜色映射
- `web/src/lib/viewer.ts`：
  - 新增 `createRadialGradientTexture(center, edge)` 生成径向渐变 `CanvasTexture`
  - `Viewer3D.options.background` → `backgroundCenter` + `backgroundEdge`
  - 构造函数用渐变纹理替代 `THREE.Color`
  - `setBackground(center, edge)` 重建渐变纹理
  - `dispose()` 清理纹理
- `web/src/components/three-viewer.tsx`：`background` prop → `backgroundCenter` + `backgroundEdge`
- `web/src/pages/generate-page.tsx`：去掉 `getComputedStyle`，使用 `useViewerColors()`
- `web/src/pages/viewer-page.tsx`：同上
- `web/src/components/task-sheet.tsx`：同上

## Notes
- dark 渐变：中心 `#222228`，边缘 `#111114`
- light 渐变：中心 `#f4f4f7`，边缘 `#e0e0e4`
- 渐变纹理固定 512x512，不跟 canvas 尺寸走，GPU 开销可忽略
- 构建验证通过
