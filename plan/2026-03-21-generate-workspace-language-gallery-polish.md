# Generate 页面文案与布局优化 + 语言选择器改进
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
- 将用户侧顶部导航中的 Generate/生成 统一升级为 Workspace/工作台（仅文案，不改路由）。
- 移除 Generate 左侧面板中不应对外暴露的 coming soon 占位信息，收紧操作路径。
- 优化语言切换菜单可理解性：选项始终显示语言原生名称，并更换更直观的语言图标。
- 统一 Gallery 页面标题区与内容区的宽度约束，修复视觉不一致。

## Key Decisions
- 保持 `/generate` 路由不变，仅更新 `shell.nav.generate` 与 `user.shell.nav.generate` 的中英文文案。
- 直接删除 `user.generate.panel.comingSoon` i18n key 与页面引用，避免残留“路线图”内容。
- 在 `LOCALE_OPTIONS` 增加 `nativeName` 字段，由 UI 直接渲染，不再依赖当前语言下的翻译文案。
- Gallery 采用单一 `max-w-7xl mx-auto` 容器包裹标题、筛选、网格与 load more，确保宽度一致。

## Changes
- `web/src/i18n/en.json`
  - `shell.nav.generate`：`Generate` → `Workspace`
  - `user.shell.nav.generate`：`Generate` → `Workspace`
  - 删除 `user.generate.panel.comingSoon`
- `web/src/i18n/zh-CN.json`
  - `shell.nav.generate`：`生成` → `工作台`
  - `user.shell.nav.generate`：`生成` → `工作台`
  - 删除 `user.generate.panel.comingSoon`
- `web/src/pages/generate-page.tsx`
  - 删除左侧 panel 的 coming soon 占位 `<div>`
  - 生成按钮容器从 `mt-auto pt-4` 调整为 `mt-4`
- `web/src/hooks/use-locale.ts`
  - `LOCALE_OPTIONS` 新增 `nativeName` 字段（`English` / `简体中文`）
- `web/src/components/layout/user-shell.tsx`
  - 语言按钮图标 `Globe2` 更换为 `Languages`
  - 语言菜单选项改为显示 `locale.nativeName`
- `web/src/pages/gallery-page.tsx`
  - 页面内容改为统一置于 `max-w-7xl mx-auto` 容器内（标题 + filters + grid + load more）

## Notes
- 构建验证通过：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
