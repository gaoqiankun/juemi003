# 生成页专业查看器升级 + 左侧配置面板重构 + 无边界画布
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
- 升级 `ModelViewport` 为更专业的查看器控制：ACES 渲染、显示模式切换、灯光调节、背景预设。
- 将生成页左侧从“纯上传区”改成“紧凑生成配置面板”。
- 将中间区域改成无边框无圆角的全出血画布，并让左右面板浮在画布上层。

## Key Decisions
- 显示模式采用 `texture / clay / wireframe` 三选一：
  - clay 通过替换 mesh 材质实现（统一灰白 PBR 参数）；
  - wireframe 采用 clay 基底 + `WireframeGeometry + LineSegments` 叠加，视觉可读性更好。
- 为避免每次切模式丢状态，给每个 mesh 缓存原材质与当前覆盖材质（切回 texture 时恢复并回收覆盖材质）。
- 灯光控制按“灯光组（Group）绕 Y 轴旋转”实现 `setLightAngle(0~360)`，强度支持 `setLightIntensity(0~1.5)`。
- 背景预设放在 `ModelViewport` 本地状态中：用户手动选过后优先使用手动背景，主题切换时不覆盖；未手动选择时继续跟随 `useViewerColors()`。
- 生成页布局改成“画布底层 + 面板浮层”结构，保留各 generateView 状态渲染逻辑不变。

## Changes
- `web/src/lib/viewer.ts`
  - 明确使用 `THREE.ACESFilmicToneMapping`，曝光收敛到 `1.0`。
  - 新增 `ViewerDisplayMode` 与查看器接口：`setDisplayMode` / `setLightIntensity` / `setLightAngle`。
  - 新增材质覆盖与恢复逻辑、wireframe 叠加层创建和销毁逻辑。
  - 灯光改为挂在 `rig` 下，通过 `rig.rotation.y` 统一旋转。
- `web/src/components/three-viewer.tsx`
  - 新增 `displayMode` / `lightIntensity` / `lightAngle` props 并透传至 `Viewer3D`。
- `web/src/components/model-viewport.tsx`
  - 工具栏重构为三组：
    - 左：`Texture | Clay | Wireframe` segmented control
    - 中：`Orbit` / `Grid` / `Reset`
    - 右：`Light` / `Background` icon + Popover
  - 灯光 Popover：强度滑条、角度滑条、重置按钮（实时生效）。
  - 背景 Popover：6 个渐变预设 + “跟随主题”选项。
- `web/src/pages/generate-page.tsx`
  - 左侧重构为紧凑配置面板：固定高度上传区、模型选择器、扩展占位区、底部生成按钮。
  - 中间改为无边框无圆角全出血画布。
  - 左右面板改为毛玻璃浮层（`z-10` + glass card）。
- `web/src/i18n/en.json`
- `web/src/i18n/zh-CN.json`
  - 补充生成页 panel 文案、viewer 工具栏新增文案（显示模式、灯光、背景预设）。

## Notes
- 未修改 `web/src/pages/viewer-page.tsx` 与 `web/src/components/task-sheet.tsx`。
- 构建验证通过：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
