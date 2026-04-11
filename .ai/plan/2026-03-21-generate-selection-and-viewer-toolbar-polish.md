# Generate 页选择状态修复 + Viewer 工具栏优化
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
- 修复生成页进入时自动选中历史活跃任务的问题，确保初始展示 idle 空状态引导。
- 重构模型查看器底部工具栏，去掉非专业操作，补齐重置视角能力，并优化网格表现。

## Key Decisions
- 在 provider 新增 `clearCurrentTaskSelection({ lockAutoSync })`，并引入 `autoSelectionLockedRef`：
  - 进入生成页时锁定自动选择，防止 `syncCurrentTaskSelection()` 在任务刷新后把空状态恢复成历史任务。
  - 用户主动点历史任务或提交新任务时通过 `setCurrentTaskId(taskId)` 解锁自动选择。
- 在 terminal 状态（completed/failed/cancelled）下：
  - 上传新图片时清空旧 `currentTaskId` 并锁定自动选择，回到流程态。
  - 点击重试时先清空旧选择，再创建新任务。
- 工具栏改为三项：自动旋转、网格、重置视角；去掉放大和光照开关。
- 网格从 `THREE.GridHelper` 改为自绘 canvas 纹理平面：
  - 中心轴线更强，外圈线条按距离衰减并叠加径向 alpha mask，避免“硬截断”。
- 在 `Viewer3D` 增加 `resetCamera()`（平滑动画回到模型默认 framing），`ThreeViewerHandle` 暴露 `resetCamera`，移除 `zoomIn` 暴露。

## Changes
- `web/src/app/gen3d-provider.tsx`
  - 增加 `clearCurrentTaskSelection` context API。
  - 增加并接入 `autoSelectionLockedRef`，修正任务刷新/快照更新时的自动选中行为。
  - `selectFile` 与 `retryCurrentTask` 在 terminal 场景下清空旧选择并回到生成流程。
- `web/src/pages/generate-page.tsx`
  - 页面挂载时调用 `clearCurrentTaskSelection({ lockAutoSync: true })`，确保进入页面即 idle 空状态。
- `web/src/components/model-viewport.tsx`
  - 工具栏按钮改为：`orbit` / `grid` / `reset`。
  - 删除 zoom 与 lighting 交互按钮。
- `web/src/components/three-viewer.tsx`
  - `ThreeViewerHandle` 从 `zoomIn` 改为 `resetCamera`。
  - 移除 `lightingEnabled` prop 控制（默认保持开启）。
- `web/src/lib/viewer.ts`
  - 新增平滑 `resetCamera()` 动画逻辑与默认相机位缓存。
  - 网格渲染升级为带径向渐隐的纹理平面，并补充对应销毁逻辑。
- `web/src/i18n/en.json`
- `web/src/i18n/zh-CN.json`
  - 新增 `user.viewer.toolbar.reset` 文案，移除旧 zoom/light toolbar 文案。
- `web/src/pages/proof-shots-page.tsx`
- `web/src/pages/reference-compare-page.tsx`
  - 同步补齐 `Gen3dContextValue` 新字段 `clearCurrentTaskSelection` 的 mock 实现（noop）。

## Notes
- 未修改 `web/src/pages/viewer-page.tsx` 与 `web/src/components/task-sheet.tsx`。
- 构建验证通过：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
