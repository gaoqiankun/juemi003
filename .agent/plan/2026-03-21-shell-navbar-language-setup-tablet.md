# 导航栏重设计 + 语言下拉 + 设置页返回 + 平板适配
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
- 重构用户端 shell 导航栏：提升层级感，补齐主导航和右侧工具区。
- 将语言切换从循环 toggle 改为可见可选的下拉选择。
- 为设置页补充取消/返回操作，避免用户被困在表单页。
- 优化生成页在 768px~1279px 区间的交互布局，保持画布优先并提升侧栏可用性。

## Key Decisions
- 运行时主壳使用 `web/src/components/layout/user-shell.tsx`，此处作为导航重构主落点；`web/src/components/app-shell.tsx` 同步视觉结构，保证对比页/演示页一致。
- 导航激活态使用“路径前缀 + token 化背景”方案（`/generate` 覆盖 `/setup`，`/gallery` 覆盖 `/viewer/*`），避免路由层级变化导致高亮错位。
- 语言切换统一依赖 `useLocale` 暴露的 `locales` 配置，当前为 `en / zh-CN`，便于后续扩展语言时不改 UI 结构。
- 生成页平板布局采用“左侧配置卡固定浮层 + 右侧历史按钮触发抽屉”方案；抽屉支持遮罩点击和 `Esc` 关闭。

## Changes
- `web/src/components/layout/user-shell.tsx`
  - 顶栏改为 64px、左中右三段：品牌、主导航（Generate/Gallery）、工具区（语言下拉/主题/设置+连接状态点）。
  - 使用设计 token（`bg-surface`、`border-outline`、`text-*`），并加半透明 + blur 质感。
  - 修复设置按钮激活态逻辑（基于当前路径判断，避免 `Link` 上误用 `isActive` 回调）。
- `web/src/components/app-shell.tsx`
  - 同步导航结构与视觉风格，补齐语言下拉与主导航激活态表现，保持与运行时壳一致。
- `web/src/hooks/use-locale.ts`
  - 新增 `LOCALE_OPTIONS` 并向外暴露 `locales`，供 header 下拉渲染。
- `web/src/pages/setup-page.tsx`
  - 新增取消按钮（secondary），优先 `navigate(-1)`；无历史时回到 `location.state.from` 或 `/generate`。
- `web/src/pages/generate-page.tsx`
  - 平板区间（`md`~`xl`）改为全屏画布 + 左侧浮动配置面板 + 右侧历史悬浮按钮/抽屉。
  - 增加抽屉开关状态、遮罩交互与 `Esc` 关闭处理。
- `web/src/pages/viewer-page.tsx`
  - 调整平板相关断点的侧栏宽度与网格切换时机，提升 10~12 寸设备的可用性。
- `web/src/i18n/en.json`
- `web/src/i18n/zh-CN.json`
  - 新增“打开最近/关闭最近”“取消”等文案，补齐导航与设置页文案需求。

## Notes
- 构建验证通过：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
