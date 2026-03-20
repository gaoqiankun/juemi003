# 用户页恢复到 M2 之前
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
按指定 commit `0b6f1f2` 恢复用户页相关前端文件到 M2 改动之前的状态，并验证前端构建与生成页视觉结果。

## Key Decisions

- 仅恢复用户明确指定的 4 个文件：
- `web/src/pages/generate-page.tsx`
- `web/src/components/app-shell.tsx`
- `web/src/main.tsx`
- `web/src/styles.css`
- 不触碰仓库内其他未提交改动，避免把当前并行工作一并回退

## Changes

- 执行 `git checkout 0b6f1f2 -- web/src/pages/generate-page.tsx web/src/components/app-shell.tsx web/src/main.tsx web/src/styles.css`
- 新增本次恢复记录，便于后续追踪为何用户页样式与入口代码回退
- 按最新要求将 `web/src/main.tsx` 恢复到带 `ThemeProvider + i18n` 的 M2 入口，并补回 `Gen3dProvider`，消除原始生成页的 runtime context 缺失
- 将 `web/src/styles.css` 恢复到 M2 token/theme 基线，重新启用 `tokens.css`、user shell、toolbar 与 admin primitives 风格
- 在不改三栏 DOM 结构的前提下，重做 `web/src/pages/generate-page.tsx` 的视觉层：
- 左侧上传区、中央空状态/进度/完成态、右侧最近生成列表全部改为 CSS variable 驱动
- 生成页按钮、卡片、边框、文本、状态色与 Admin 主题变量对齐
- Three.js viewer 背景色改为读取当前主题下的 `--surface-container-lowest`
- 调整 `web/src/components/layout/user-shell.tsx` 导航头部：
- 品牌区去掉“创作工作台”副标题，仅保留图标 + `Cubie 3D`
- 顶部导航只保留“生成”和“我的生成”
- `/setup` 入口改到右侧 toolbar 的独立齿轮按钮
- 在 `web/src/styles.css` 增加 `toolbar-icon-button` 样式，保证 settings 按钮尺寸与单行 header 节奏一致

## Notes

- 需要在 `web/` 目录执行 `npm run build` 验证构建
- 需要启动本地页面并截图确认 `/generate` 当前样式
- 2026-03-21 本地验证：
- `npm run build` 通过
- Playwright 实测 `/setup -> /generate` 可进入生成页
- 深浅主题切换生效；最终验收截图保存在 `output/playwright/m2-generate-visual/.playwright-cli/page-2026-03-20T17-21-59-759Z.png`
- user shell 头部导航修正后，Playwright 验收截图保存在 `output/playwright/user-shell-nav-fix/.playwright-cli/page-2026-03-20T17-28-38-606Z.png`
