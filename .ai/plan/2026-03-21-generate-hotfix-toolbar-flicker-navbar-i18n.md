# 生成页紧急修复：操作条遮挡 + 闪烁 + 导航栏 + i18n 补全
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
- 修复生成页 completed 状态操作条与 `ModelViewport` 底部工具栏冲突问题。
- 修复模型加载默认自动旋转与加载阶段闪烁问题。
- 调整用户端导航栏，移除中部导航并将语言切换改为 Globe 按钮 Popover。
- 补齐指定页面与组件的 i18n，移除目标文件中的硬编码中英文 UI 文案（`Trellis v2` 保留）。

## Key Decisions
- completed 操作按钮改为放在左侧生成配置面板底部，避免占用画布区域；保留生成按钮，支持用户直接再次生成。
- 关闭查看器 bloom 后处理，保留 ACES 色调映射，降低模型 fade-in 阶段高光闪烁风险。
- 语言切换改为与主题按钮一致的 icon 工具按钮样式，使用自定义 Popover（支持外部点击和 Esc 关闭）。
- 查看器运行时状态与错误文案统一迁移到 i18n key，`viewer.ts` 通过 i18n 实例读取文案。

## Changes
- `web/src/pages/generate-page.tsx`
  - 移除 completed 状态下画布底部浮动下载/重试/详情条，避免与 `ModelViewport` 底部工具栏重叠。
  - 在左侧配置面板底部新增 completed 动作组：下载（primary）、重试（secondary）、详情（ghost）。
  - 指定硬编码文案改为 `t()`：最近生成、全部、暂无记录、上传引导、生成中、模型准备中、重试/详情、失败提示等。
- `web/src/components/model-viewport.tsx`
  - `autoRotate` 默认值由 `true` 改为 `false`。
- `web/src/lib/viewer.ts`
  - 移除 `UnrealBloomPass` 与 composer 渲染链，改为直接 `renderer.render(scene, camera)`。
  - 运行时状态与错误提示文案改为 i18n key（含缓存读取、下载进度、解析、重试与错误信息）。
- `web/src/components/layout/user-shell.tsx`
  - 删除 header 中间 `Generate / Gallery` 导航。
  - 语言切换从原生 `<select>` 改为 Globe icon 按钮 + Popover 列表（当前语言 check 标记，选择后自动关闭，点外部关闭）。
- `web/src/components/task-sheet.tsx`
  - 指定 5 处文案改为 `t()`，并复用 `user.generate.status.modelPreparing`、`user.viewer.actions.download`、`user.gallery.delete`。
- `web/src/pages/viewer-page.tsx`
  - FORMAT_OPTIONS 的 label/description 改为 i18n key。
- `web/src/i18n/en.json`
- `web/src/i18n/zh-CN.json`
  - 新增 generate/task-sheet/viewer format/nav language/runtime viewer 所需文案 key。

## Notes
- 构建验证通过：
  - `cd web && PATH=\"$HOME/.nvm/versions/node/v24.14.0/bin:$PATH\" npm run build`
