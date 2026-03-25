# Viewer Screen 重建
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
按 `design/user-dark.html` 的 `ViewerScreen` 重建 `web/src/pages/viewer-page.tsx`，接入真实任务数据与现有 three viewer，不改后端协议。

## Key Decisions

- 数据源固定走 `useGen3d().taskMap[taskId]`，路由参数为 `/viewer/:taskId`
- 3D 视口继续复用 `ThreeViewer` / `Viewer3D`，只补 viewer 控件能力，不另起一套实现
- 页面样式全部走现有 token 体系，按钮、面板、glass toolbar 不写页面级硬编码色
- 导出区保留三类动作：
- `Download GLB` 直接走现有 artifact 下载链接
- `Export OBJ` 无产物时仍渲染 disabled 按钮
- `EXPORT TO ENGINE` 只做 UI，占位 toast `即将推出`

## Changes

- 重写 `web/src/pages/viewer-page.tsx`
- 中央主区域改为全屏模型视口，顶部覆盖返回模型库按钮和模型 ID badge
- 底部新增玻璃态悬浮工具栏，提供 orbit / zoom / grid / lighting 切换
- 右侧新增固定宽度信息面板，展示文件名、任务 ID、状态、面数、文件大小、更新时间和导出按钮
- `web/src/components/three-viewer.tsx`
- 改为 `forwardRef`，暴露 `zoomIn()` 给 viewer 工具栏
- 支持 `autoRotate`、`showGrid`、`lightingEnabled`、grid 颜色和模型统计回调
- 修正 viewer 生命周期，避免切换 orbit/grid/light 时重建整个 Three.js viewer
- `web/src/lib/viewer.ts`
- 补充 grid、lighting、zoom、模型统计、主题背景与 token 化的 overlay/message 样式能力
- `web/src/i18n/en.json`
- `web/src/i18n/zh-CN.json`
- 补齐 viewer 区域标题、工具栏 aria label、导出按钮和 toast 文案

## Notes

- 本地 `web/` 构建已通过：`npm run build`
- 本地截图验收已跑通页面布局，但用于验收的历史 task 在当前环境下请求 `/v1/tasks/{id}/artifacts/model.glb` 返回 404，导致截图里是 viewer 错误提示而不是已加载模型；用户已要求停止继续排查可用 task
