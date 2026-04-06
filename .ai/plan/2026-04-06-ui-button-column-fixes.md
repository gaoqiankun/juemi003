# UI — Button Icon-Only + Column Width Fixes
Date: 2026-04-06
Status: approved

## Goal

models-page.tsx 两处 UI 修正：
1. 操作按钮（Delete / Retry / Remove）去掉文字，只保留图标
2. 调整表格列宽，给 actions 列更多空间

## 变更细节

### 按钮图标化（`web/src/pages/models-page.tsx`）

主表格 Delete 按钮（~line 552-561）：
- 移除 `{t("models.list.delete")}` 文字
- 图标 `<Trash2>` 去掉 `mr-1`
- 加 `title={t("models.list.delete")}` 作为 tooltip

Pending 区域（~line 188-205）：
- Retry 按钮：移除文字，图标去 `mr-1`，加 `title`
- Remove 按钮：移除文字，图标去 `mr-1`，加 `title`

Cancel 按钮（~line 177-185）：**保持不变**（有文字"取消"比较重要）

### 列宽（`<colgroup>` ~line 458-463）

当前：34% / 20% / 14% / 32%
改为：**30% / 10% / 8% / 52%**

## 文件范围

- `web/src/pages/models-page.tsx` — 仅上述改动
- 不改 i18n 文件（key 保留，用于 title tooltip）
- 不改其他文件

## Acceptance Criteria

- [ ] 主表格 Delete 只显示垃圾桶图标，hover 有 tooltip
- [ ] Pending Retry / Remove 只显示图标，hover 有 tooltip
- [ ] 列宽：runtime 和 slot 列明显更窄，actions 列更宽
- [ ] `npm run build` zero errors / warnings
