# Admin Models UI Polish
Date: 2026-03-29
Status: done
Commits: N/A（按 AGENTS.md 要求不执行 commit）

## Goal
按任务要求修复 Admin Models 页 UI：
- Add Model 对话框移除 ID/Min VRAM 输入并更新文案
- 模型列表增加 provider type 徽章与 resolved path 优先展示
- 同步前端类型与映射字段（provider_type / resolved_path）
- 保持仅前端改动，不改后端

## Planned Files
- `web/src/components/add-model-dialog.tsx`
- `web/src/pages/models-page.tsx`
- `web/src/hooks/use-models-data.ts`
- `web/src/lib/admin-api.ts`
- `web/src/i18n/zh-CN.json`
- `web/src/i18n/en.json`
- `.ai/tmp/report-models-ui-polish.md`

## Acceptance Criteria
1. Add Model 不渲染 ID 输入框，保留 auto-gen 逻辑。
2. Add Model 不渲染 Min VRAM 输入框，提交 payload 不发送该字段。
3. Add Model 文案更新：
   - 显示名 -> 模型名称
   - 提供方 -> 模型类型
   - 权重来源 url 选项文案 -> 下载链接
   - 权重来源 url placeholder -> `https://example.com/model.tar.gz`
4. Add Model 布局移除原 ID / Min VRAM 占位，保持合理单行/双列布局。
5. 模型列表 `sourceLabelMap.url` 显示为“链接”。
6. 前端类型补齐：`AdminModelItem.providerType/resolvedPath` 与 `RawAdminModelRecord.provider_type/resolved_path`，并在 `splitModels` 完成映射。
7. 列表名称单元格在来源徽章旁新增模型类型徽章（TRELLIS2 / HunYuan3D-2 / Step1X-3D）。
8. 路径列优先显示 `resolvedPath`，为空则回退 `modelPath`，tooltip 展示完整路径。
9. `cd web && npm run build` 零错误。

## Result
- 已完成 6 个目标前端文件改动，未改后端。
- 构建验证通过：`cd web && npm run build`（TypeScript + Vite 零错误）。
