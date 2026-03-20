# M2 Patch · 组件层重建（Radix + Tailwind + CVA）
Date: 2026-03-21
Status: done

## Goal
M2/M2.5 的 AI Coder 丢弃了原有的 Radix UI + Tailwind + CVA 技术栈，自己从头写了 primitives.tsx 和大量手写 CSS class，导致组件不系统、功能残缺、难以维护。本次在保留所有功能逻辑和 i18n 的前提下，重建组件层。

## Key Decisions

- **tokens.css 不动**：CSS 变量继续作为唯一设计 token 来源
- **tailwind.config.ts 注册变量**：把 CSS 变量映射成 Tailwind 语义色彩，所有组件用 Tailwind class 写
- **Radix UI + CVA 重建 primitives**：Button / Badge / Dialog / Tabs / Input / Select / Switch 等用 Radix + CVA 实现，和 shadcn/ui 模式一致
- **保留功能和 i18n**：所有页面逻辑、hook、i18n key 不动，只替换组件和样式

## Changes

- `web/tailwind.config.ts`
  - 注册 `tokens.css` 的语义颜色映射，补上 `surface.*`、`accent.*`、`text.*`、`success|warning|danger`、`outline`、`background` 等 Tailwind token
  - `darkMode` 改为兼容 `data-theme="dark"`，让 ThemeProvider 切换直接驱动 Tailwind class
- `web/src/components/ui/*`
  - 用 Radix UI + CVA 重建 `button / badge / card / input / select / switch / dialog / tabs / sheet / alert-dialog`
  - `Button` 支持 `loading`，并修复 `asChild` 下 `React.Children.only` 运行时错误
  - `primitives.tsx` 重写为 shadcn/ui 风格薄包装层，保留业务页面使用的 `Button / Badge / StatusDot / Card / TextField / SelectField / ToggleSwitch / MeterBar / Tabs / Dialog`
- `web/src/components/layout/user-shell.tsx`
  - 去掉副标题，只保留图标 + `Cubie 3D`
  - 导航只留 `Generate` / `My Generations`
  - `/setup` 改成右上角齿轮按钮
  - header 改为全宽贴顶 + `border-b`
- `web/src/components/layout/admin-shell.tsx`
  - 整体改成 token 驱动的 Tailwind 布局，左侧导航 / 顶部 toolbar / 语言和主题切换全部迁回统一 primitives 风格
- 页面迁移到 Tailwind + primitives：
  - `dashboard-page.tsx`
  - `tasks-page.tsx`
  - `models-page.tsx`
  - `api-keys-page.tsx`
  - `settings-page.tsx`
  - `setup-page.tsx`
  - `generate-page.tsx`
  - `generations-page.tsx`
  - `viewer-page.tsx`
- 视觉组件细化：
  - `task-thumbnail.tsx`、`three-viewer.tsx`、`progress-particle-stage.tsx` 改为跟随 token / 主题
  - `badge.tsx` 去掉不稳定的 `/opacity` token 写法，改为显式 `color-mix(...)`
- 依赖补齐：
  - 安装 `@radix-ui/react-select`
  - 安装 `@radix-ui/react-switch`
- 验收：
  - `web/` 下 `npm run build` 通过
  - 截图输出目录：`output/playwright/m2-component-rebuild/`
  - 关键截图：
    - `setup-light.png`
    - `generate-light.png`
    - `generate-dark.png`
    - `generations-dark.png`
    - `viewer-dark.png`
    - `admin-dashboard-light.png`
    - `admin-tasks-light.png`
    - `admin-models-light.png`
    - `admin-api-keys-light.png`
    - `admin-settings-light.png`

## Notes

- tailwind.config.ts 的 colors 扩展示例：
  `surface: 'var(--surface)'`、`accent: 'var(--accent)'`、`'text-primary': 'var(--text-primary)'`
- 原有依赖列表并不完整，实际补装了 `@radix-ui/react-select` 和 `@radix-ui/react-switch`
- primitives.tsx 可以重写为 shadcn/ui 风格的薄包装层
- npm run build 必须通过，无 TypeScript 报错
