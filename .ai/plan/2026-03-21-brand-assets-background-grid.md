# 品牌统一 + 背景选择器优化 + 浅色网格 + 术语统一
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
- 将前端产品显示品牌从旧命名（带 3D 后缀）统一为“Cubie”。
- 将 Gallery/历史/模型库 的用户侧文案统一为 Assets/资产。
- 优化 Viewer 背景预设选择器为紧凑色点，并支持自定义取色。
- 提升浅色模式下网格线可见性。

## Key Decisions
- 仅改动用户可见的 Web 文案与组件，不改动路由路径（继续使用 `/gallery`）。
- 背景自定义采用单一取色器：用户选择中心色，边缘色由代码自动生成稍暗变体（约 14%）。
- 浅色网格主线颜色改为半透明黑（`rgba(0, 0, 0, 0.14)`），保证在浅底上可辨识。

## Changes
- `web/index.html`
  - 页面标题改为 `Cubie`。
- `web/src/components/layout/user-shell.tsx`
  - 用户端 Logo `alt` 与品牌文字改为 `Cubie`。
- `web/src/components/layout/admin-shell.tsx`
  - 管理端 Logo `alt` 与品牌文字改为 `Cubie`。
- `web/src/components/app-shell.tsx`
  - AppShell Logo `alt` 与品牌文字改为 `Cubie`。
- `web/src/components/model-viewport.tsx`
  - 背景预设改为紧凑圆形色点（无显式文字，使用 title/aria-label）。
  - 保留“跟随主题”按钮。
  - 新增自定义颜色点（`input[type=color]`），并自动推导 edge 颜色。
- `web/src/hooks/use-viewer-colors.ts`
  - 浅色主题 `gridPrimary` 调整为 `rgba(0, 0, 0, 0.14)`。
- `web/src/i18n/en.json`
  - 品牌文案改为 `Cubie`。
  - `gallery` 导航与相关用户文案统一为 `Assets`。
  - viewer 返回与面包屑改为 `Back to Assets` / `Assets`。
  - 新增 `user.viewer.toolbar.background.custom`。
  - setup 描述中的旧品牌写法改为 `Cubie`。
- `web/src/i18n/zh-CN.json`
  - 品牌文案改为 `Cubie`。
  - `gallery` 导航与相关用户文案统一为 `资产`。
  - viewer 返回与面包屑改为 `返回资产` / `资产`。
  - 新增 `user.viewer.toolbar.background.custom`（`自定义`）。
  - setup 描述中的旧品牌写法改为 `Cubie`。

## Notes
- 验证命令：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
- 构建结果：通过。
- 旧品牌词检索（web 范围）无结果。
