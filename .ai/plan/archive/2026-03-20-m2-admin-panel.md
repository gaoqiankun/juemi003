# M2 · Admin Panel 实现
Date / Status: 2026-03-20 / done / Commits: not committed in this session

## Goal
在现有 `web/` React 应用基础上，实现完整的 Cubify 3D Admin Panel，包含 5 个页面的双主题（Dark/Light）支持，设计参考已导出的 Stitch 设计稿和 DESIGN.md 规范文件。

## Key Decisions

- **设计参考**：`Cubify-Dark-DESIGN.md` + `Cubify-Light-DESIGN.md` + `stitch-dark.zip` + `stitch-light.zip`
- **主题系统**：CSS 变量（design tokens）实现，单文件切换 Dark/Light，未来可扩展更多主题；accent 颜色用一个变量控制（默认 Teal #0891B2）
- **路由**：5 个页面（Dashboard / Tasks / Models / API Keys / Settings），用现有路由方案扩展
- **i18n**：react-i18next，en + zh-CN，内置 bundle（不做懒加载）
- **中文字体**：Noto Sans SC（fallback: PingFang SC, Microsoft YaHei），Latin 用 Inter / Geist
- **图标**：Lucide React（轻量，Tree-shakeable）
- **数据**：全部 mock 数据，不接真实 API（API 层留占位 hook，后续替换）

## 设计规范摘要（AI Coder 参考）

### Dark Theme Tokens
- `surface`: #131316
- `surface-container-low`: #1b1b1e（sidebar）
- `surface-container-highest`: #353438（interactive card）
- `primary` accent: #0891B2（Teal），CTA 用渐变 #6cd3f7 → #269dbe
- 无 1px 实线分隔，用背景色分层

### Light Theme Tokens
- `background`: #f9f9fb
- `surface-container` (sidebar): #eeeef0
- `surface-container-lowest` (cards): #ffffff
- `primary` accent: #0891B2，CTA 渐变 #00647c → #007f9d
- 无 1px 实线分隔，用背景色分层

### 通用规则
- 圆角：6px（全局统一）
- 字体：Inter（-0.02em tracking），Geist Mono（IDs/Hash），Space Grotesk（labels）
- 数字：`font-variant-numeric: tabular-nums`
- Floating 元素（Modal/Tooltip）：Glassmorphism，60% opacity + 20px backdrop-blur
- 状态点：6px 圆点 + lowercase 文字，无 glow

## 5 个页面功能范围

| 页面 | 核心内容 |
|------|---------|
| Dashboard | 4 个 stats 卡（Active Tasks / Queued / Completed / Failed）+ GPU 卡（NVIDIA RTX，VRAM bar，TEMP/POWER/FANS/CUDA）+ Recent Tasks 表 + Infrastructure Nodes |
| Tasks | 队列统计（throughput/latency/count）+ 任务列表（带状态 filter）+ 日志区 |
| Models | 模型卡片网格（TRELLIS2/HunYuan3D 等）+ 下载状态 + Import 入口 |
| API Keys | 用量统计 + key 列表（名称/创建时间/用量/操作）+ Create Key |
| Settings | 分组表单（Generation Engine / Storage / Traffic & Limits）+ toggle/input 组件 |

## Changes

- `web/src/App.tsx` 改成 5 页面 admin 路由：`/dashboard`、`/tasks`、`/models`、`/api-keys`、`/settings`，并给 `BrowserRouter` 打开 React Router v7 future flags，消除 dev warning
- `web/src/main.tsx` 移除旧的 `Gen3dProvider` 和 toaster 依赖，入口改为 `ThemeProvider + react-i18next`
- 新增 `web/src/styles/tokens.css`，用 `:root[data-theme="dark/light"]` 承载双主题 design tokens；`web/src/styles.css` 全量重写为 No-Line、6px radius、tonal layering 风格
- 新增 `web/src/components/layout/admin-shell.tsx`，实现 Sidebar + Topbar + Theme/Language toggle；主题持久化到 `localStorage`
- 新增 `web/src/components/ui/primitives.tsx`，封装 Card / Button / Badge / StatusDot / MeterBar / TextField / SelectField / ToggleSwitch
- 新增 `web/src/pages/dashboard-page.tsx`、`tasks-page.tsx`、`models-page.tsx`、`api-keys-page.tsx`，重写 `settings-page.tsx`，全部改为 mock 数据管理面板
- 新增 `web/src/data/admin-mocks.ts` 与 `web/src/hooks/useXxxData.ts` 系列 hook，统一 mock 数据边界，方便后续替换真实 API
- 新增 `web/src/i18n/index.ts`、`en.json`、`zh-CN.json`，接入 `react-i18next`
- 新增 `web/src/hooks/use-theme.tsx`、`web/src/hooks/use-locale.ts` 和 `web/src/lib/admin-format.ts`
- `web/package.json` / `web/package-lock.json` 增加 `i18next`、`react-i18next`

## Notes

- 设计稿 zip 在 `gen3d/stitch-dark.zip` 和 `gen3d/stitch-light.zip`，解压后有 Stitch 导出的 React 代码可参考组件结构，但不要直接使用（代码质量不稳定），以 DESIGN.md 为准
- API Keys 页面注意不展示真实密钥（mask 处理）
- Dashboard GPU 卡数据全部 mock，结构对齐后端 `/api/v1/system/info` 响应格式（待定）
- 主题切换保存到 localStorage
- 验证结果：
- `web/` 下执行 `npm run build` 通过
- 本地起 `npm run dev -- --host 127.0.0.1 --port 4173`，因 4173 被占用自动切到 `http://127.0.0.1:4174/static/`
- 使用 Playwright CLI 验证 `/dashboard`、`/tasks`、`/models`、`/api-keys`、`/settings` 五个路由均可访问，Page Title 均为 `Cubify 3D`
- 在浏览器中实际点击主题 / 语言按钮后，`localStorage` 中可见 `cubify3d-admin-theme=dark`、`cubify3d-admin-language=en`
- 新建 Playwright 会话重新打开 `/dashboard` 后控制台为 `0 errors`；旧会话里的 2 条 warning 已通过 React Router future flags 消除
- 后续补丁已把 admin 路由统一收口到 `/admin/*`：`/admin/dashboard`、`/admin/tasks`、`/admin/models`、`/admin/api-keys`、`/admin/settings`
- 针对路由前缀补丁，`npm run build` 再次通过；Playwright 实测 `http://127.0.0.1:4176/static/admin/dashboard` 可访问；根路径 `/` 在已配置 `cubify3d-api-key` 的会话里会落到 `/generate`
