# Viewer 第二轮细节打磨 + i18n 修复
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
- 优化 Viewer sidebar 信息密度与可扩展性（StatCard 紧凑化、导出格式改下拉）。
- 调整浅色模式 viewer 背景渐变，降低聚光灯感。
- 修复中文 `Clay` 显示为英文的问题。

## Key Decisions
- 导出格式切换从 radio-card 改为 Radix `Select`，为后续格式扩展（FBX/STL/USDZ）预留空间。
- `MODIFIED` 继续使用相对时间，确保小尺寸 stat card 文案不溢出。
- 浅色背景采用更接近的中心/边缘色值，优先“均匀柔和”观感。

## Changes
- `web/src/pages/viewer-page.tsx`
  - `StatCard` 改为“图标+标签同行、数值在下”的紧凑布局，缩小 card padding/gap。
  - 导出格式区域改为 Radix `Select`（`SelectTrigger / SelectContent / SelectItem`）。
  - 删除原 radio card 样式逻辑。
- `web/src/hooks/use-viewer-colors.ts`
  - 浅色主题背景：`#f7f7fa/#dddde2` 调整为 `#eeeff3/#e4e5ea`，减小中心到边缘色差。
- `web/src/i18n/zh-CN.json`
  - `user.viewer.toolbar.displayMode.clay`：`Clay` → `素模`。

## Notes
- 构建验证通过：
  - `cd web && PATH=\"$HOME/.nvm/versions/node/v24.14.0/bin:$PATH\" npm run build`
