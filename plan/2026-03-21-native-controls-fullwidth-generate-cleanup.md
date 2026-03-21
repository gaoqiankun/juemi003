# 原生控件替换 + 全宽布局 + completed 按钮移除
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
- 删除生成页 completed 状态下左侧面板的下载/重试/详情按钮，仅保留生成主按钮逻辑。
- 将生成页模型选择器从原生 `<select>` 切换为现有 Radix/shadcn `Select` 组件。
- 将用户壳布局改为全宽，去掉 `main` 的限宽容器。
- 全局排查并移除原生 `<select>`；对 `input[type="range"]` 做统一设计系统样式化。

## Key Decisions
- completed 相关操作入口不在生成页保留，用户通过历史列表进入 viewer 执行下载与详情操作。
- 继续使用现有 `web/src/components/ui/select.tsx`，不引入新的表单体系。
- 当前项目未接入 Radix Slider 组件，灯光调节滑条采用自定义 CSS（`appearance: none` + 设计 token）实现主题一致性。

## Changes
- `web/src/pages/generate-page.tsx`
  - 删除 completed 面板中的下载/重试/详情按钮区块。
  - 移除相关状态与无用依赖（`showCompletedActions`、`useNavigate`、`Download`/`Eye` 图标）。
  - 将模型选择器替换为 `Select + SelectTrigger + SelectContent + SelectItem`。
- `web/src/components/app-shell.tsx`
  - 将语言选择从原生 `<select>` 替换为 UI `Select` 组件。
- `web/src/components/model-viewport.tsx`
  - 灯光强度/角度滑条统一使用 `viewer-range` 样式类。
- `web/src/styles.css`
  - 新增 `.viewer-range` 与 WebKit/Firefox track/thumb/focus 样式，适配亮暗主题 token。
- `web/src/components/layout/user-shell.tsx`
  - `main` 去掉 `mx-auto` 与 `max-w-[1560px]`，改为全宽内容容器。

## Notes
- 全局检索确认：
  - 已无原生 `<select>`
  - `input[type="range"]` 仅出现在 viewer 灯光面板，并使用 `viewer-range` 样式
- 构建验证通过：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
