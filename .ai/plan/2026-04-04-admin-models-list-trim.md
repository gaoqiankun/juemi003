# Admin Models List — Trim Row Info
Date: 2026-04-04
Status: done

## Goal
模型列表 name cell 信息过多（sourceLabel badge、providerTypeLabel badge、路径），这些内容在详情弹窗里都有，列表行应精简，只保留核心标识。

## Changes
`web/src/pages/models-page.tsx` — name cell（约 :455–470）：
- 保留：displayName、isDefault badge
- 删除：sourceLabel badge（`<Badge tone="neutral">{sourceLabel}</Badge>`）
- 删除：providerTypeLabel badge（`<Badge tone="neutral">{providerTypeLabel}</Badge>`）
- 删除：resolvedModelPath 那段 `<div className="mt-0.5 truncate...">`
- 同步清理 :448–451 不再被使用的 `sourceLabel`、`providerTypeLabel`、`resolvedModelPath`、`truncated` 变量

## Acceptance Criteria
1. `cd web && npm run build` 零错误
2. `cd web && npm run lint` 不新增问题
3. 列表行 name cell 只剩 displayName + isDefault badge
4. 不改其他列（runtime、slotUsage、actions）
