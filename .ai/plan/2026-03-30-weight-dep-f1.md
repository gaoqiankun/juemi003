# Weight Dependency F1
Date: 2026-03-30
Status: done
Commits: N/A（按 AGENTS.md 要求不执行 commit）

## Goal
实现 Admin Models 的 Weight Dependency F1 前端对接：
- 模型详情对话框新增只读「依赖权重」区块（deps 为空不渲染）
- Pending 下载区支持主模型 + 依赖分阶段进度显示
- 扩展前端 API 类型与 Hook 数据结构，支持 pending.deps 与模型 deps 查询
- 同步 i18n（en / zh-CN）

## Planned Files
- `web/src/lib/admin-api.ts`
- `web/src/hooks/use-models-data.ts`
- `web/src/pages/models-page.tsx`
- `web/src/i18n/en.json`
- `web/src/i18n/zh-CN.json`
- `.ai/plan/2026-03-30-weight-dep-f1.md`

## Implementation Notes
- 轮询节奏保持现状：有 pending 下载项时 2s 轮询，仅扩展渲染数据。
- `PendingModelItem.deps` 设为 optional 并在前端归一化为 `[]`，兼容 B1 后端未就绪阶段。
- `GET /api/admin/models/{id}/deps` 使用懒加载：打开详情弹窗时请求并展示。
- 当前 `models-page.tsx` 未发现现成 detail dialog，将在该页补充轻量只读详情对话框并纳入 deps 区块。

## Acceptance Checklist
1. `cd web && npm run build` 零错误
2. `cd web && npm run lint` 保持存量问题，不引入新问题
3. 新文案同步到 `en.json` 与 `zh-CN.json`
4. Pending 区支持主模型 + deps 分阶段显示（可用 mock deps 验证）
5. 详情对话框在 deps 为空数组时不渲染依赖区块
6. 改动文件 < 500 行；若超标在本文件备注

## Result
- 已实现 `admin-api.ts` / `use-models-data.ts` / `models-page.tsx` / i18n 双语增量改动，完成 F1 UI 对接。
- 新增 `fetchModelDeps(modelId)`，并把 pending 记录 `deps` 归一化为数组（后端未返回时回退 `[]`）。
- Pending 区已支持主模型与依赖分阶段状态渲染（`done/downloading/error/pending`）。
- 模型详情对话框已补充「依赖权重」只读区块；当 deps 为空数组时该区块不渲染。
- i18n key 集合已校验一致（`KEYS_MATCH`）。

## Validation
- `cd web && npm run build`：通过（零错误）。
- `cd web && npm run lint`：失败，但仅剩既有存量 15 条 `no-explicit-any`（位于 viewer 相关文件），本次改动未新增 lint 问题。

## Notes
- `web/src/pages/models-page.tsx` 当前文件总行数 641（> 500）。原因：本次在同文件内新增了详情弹窗状态管理、依赖区块渲染与 pending 分阶段行组件；为避免跨文件大重构影响并行 B1 对接，先以内聚实现交付，后续可拆分为独立组件/Hook 降低体积。
