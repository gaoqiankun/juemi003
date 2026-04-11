# Web UI 细节打磨（第五轮）：i18n、Viewer 工具栏、背景选择器、Setup 精简
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
- 完成第五轮 Web UI 细节优化：修正文案、精简 Setup 页面、优化 Viewer 工具栏与背景选择器交互，并补充阴影开关能力。
- 保持现有路由与整体视觉风格不变，只做局部体验和一致性提升。

## Key Decisions
- i18n 文案按需求精确替换，并删除不再使用的 `user.setup.description` key。
- Viewer 工具栏显示模式按钮取消内嵌背景容器，改为与图标按钮同层级排列。
- 背景弹层改为两行紧凑结构：第一行“跟随主题 + 自定义（Pipette）”，第二行保留预设色圆点。
- 阴影控制采用前端状态 `showShadow` -> `ThreeViewer` prop -> `Viewer3D.setShadowVisible()` 逐层传递，实现运行时开关。
- 亮色主题 `--page-gradient` 调整为更低饱和与更低透明度，避免偏色感和视觉喧宾。

## Changes
- `web/src/i18n/en.json`
  - `user.viewer.exportsLabel`: `Export options` -> `Export format`
  - `user.generate.recent.title`: `Recent generations` -> `Recent tasks`
  - `user.generate.empty.description`: `Generate a downloadable 3D model in minutes` -> `Generate a 3D model in minutes`
  - 新增 `user.viewer.toolbar.shadow`: `Shadow`
  - 删除 `user.setup.description`
- `web/src/i18n/zh-CN.json`
  - `user.viewer.exportsLabel`: `导出选项` -> `导出格式`
  - `user.generate.recent.title`: `最近生成` -> `最近任务`
  - `user.generate.empty.description`: `几分钟内生成可下载的 3D 模型` -> `几分钟内生成 3D 模型`
  - 新增 `user.viewer.toolbar.shadow`: `阴影`
  - 删除 `user.setup.description`
- `web/src/pages/setup-page.tsx`
  - 删除 `user.setup.description` 对应说明段落，仅保留标题与表单区域。
- `web/src/components/model-viewport.tsx`
  - 灯光按钮图标 `SunMedium` -> `Lightbulb`
  - 新增阴影开关 state `showShadow` 与工具栏按钮（`CircleDot`）
  - 显示模式按钮去掉内嵌背景框，改为同级排列
  - 背景弹层改为两行：第一行“跟随主题 + 自定义（Pipette + 文案）”，第二行预设色圆点
  - 将 `showShadow` 透传给 `ThreeViewer`
- `web/src/components/three-viewer.tsx`
  - 新增 `showShadow` prop
  - 初始化时将 `showShadow` 传入 `Viewer3D`（映射到 `shadowFloor`）
  - 新增 effect：`viewerRef.current?.setShadowVisible(showShadow)`
- `web/src/lib/viewer.ts`
  - 新增 `setShadowVisible(visible: boolean)`，统一控制 `shadowFloor` 与 `contactShadow` 的 visible
  - 加入 `shadowVisible` 状态，`setLightingEnabled` 中通过 `setShadowVisible` 协同阴影与灯光
  - 模型加载后通过 `setShadowVisible` 恢复/应用阴影状态
  - dispose 时增加阴影地面 mesh 的移除和资源释放
- `web/src/styles/tokens.css`
  - 亮色主题 `--page-gradient` 调整为更中性、更轻的渐变参数。

## Notes
- 构建验证通过：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
