# Admin 面板第七轮打磨：模型页重新设计 + 设置页紧凑布局
Date: 2026-03-22
Status: done
Commits: N/A（按仓库 AGENTS 约束，本次未执行 git commit）

## Goal
1. 模型列表页重新设计，解决布局混乱问题
2. 设置页紧凑化

## Key Decisions
- 模型列表改为 3 列：`模型名称 / 运行状态 / 启用控制`，去掉独立“默认”列。
- 默认能力内聚到名称列：
  - 默认模型在名称旁显示 `Default` badge；
  - 非默认模型在名称区域显示“设为默认”按钮。
- 运行时状态和启用状态强制分离：
  - 运行时状态仅在“运行状态”列展示（含 error 时的错误文案）；
  - 启用状态与 ToggleSwitch 放在“启用控制”列，并补充明确文字标签，避免“裸开关”。
- 设置页采用响应式紧凑网格（`md:2 列 / xl:3 列`），文本字段跨整行，减少空白但保留可读性。

## Changes
- 模型列表页重构（`web/src/pages/models-page.tsx`）
  - 表格列从 4 列调整为 3 列，移除独立默认列。
  - 名称列合并默认标识与“设为默认”入口（仅非默认模型显示按钮）。
  - 状态列只保留 runtime badge；error 状态继续展示友好错误信息。
  - 启用控制列新增带文字说明的控制块（模型访问 + 当前启用状态 + ToggleSwitch）。
- i18n 同步（`web/src/i18n/en.json`、`web/src/i18n/zh-CN.json`）
  - 模型列表列名改为 `runtime` / `availability`；
  - 新增 `models.list.enableControlLabel`；
  - 调整 `models.list.toggleLabel` 为更明确的“切换访问状态”语义。
- 设置页紧凑化（`web/src/pages/settings-page.tsx`）
  - section 卡片改为更紧凑的信息密度，增加 section 描述；
  - 字段容器由单列全宽改为响应式网格；
  - toggle 字段补充当前状态文字（active/paused）并与开关并排展示；
  - 文本字段跨多列，避免长输入框过窄。

## Notes
- 验证结果：
  - `cd web && npm run build`（Node v24.14.0）→ 通过，TypeScript 无错误
