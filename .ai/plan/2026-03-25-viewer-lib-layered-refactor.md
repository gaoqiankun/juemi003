# Viewer Lib Layered Refactor
Date / Status: 2026-03-25 / done / Commits:

## Goal
按确认分层拆分 `web/src/lib/viewer.ts`，保持对外 API 行为与导出路径不变，并通过 build/lint 验收。

## Key Decisions
- 依赖强制单向：`types/constants -> pure helpers -> loader -> runtime(class) -> facade`。
- helper 文件禁止反向依赖 runtime 类。
- `viewer.ts` 仅保留 facade re-export（<= 50 行）。

## Changes
- 新增拆分模块：
  - `web/src/lib/viewer-types.ts`
  - `web/src/lib/viewer-render-utils.ts`
  - `web/src/lib/viewer-object-utils.ts`
  - `web/src/lib/viewer-material-modes.ts`
  - `web/src/lib/viewer-lighting-env.ts`
  - `web/src/lib/viewer-floor-grid.ts`
  - `web/src/lib/viewer-model-loader.ts`
  - `web/src/lib/viewer3d-runtime.ts`
  - `web/src/lib/viewer-thumbnail.ts`
- `web/src/lib/viewer.ts` 改为 facade，仅 re-export 外部使用 API。
- 维持外部导出兼容：`Viewer3D`、`renderModelThumbnail`、`formatBytes`、`ViewerDisplayMode`、`ViewerModelStats`、光照常量。
- 将原文件中的 15 条 `no-explicit-any` 存量按原职责迁移到拆分后的 helper/runtime 文件，未新增额外 lint 类别问题。

## Notes
- 验收：
  - `cd web && npm run build` ✅
  - `cd web && npm run lint` ✅（仅剩存量 15 条 `@typescript-eslint/no-explicit-any`，总量未增加）
- `web/src/lib/viewer.ts` 当前 14 行（<= 50）。
- 本地依赖图检查 cycles=0；单向依赖满足 `types/constants -> helpers -> loader -> runtime -> facade`。
