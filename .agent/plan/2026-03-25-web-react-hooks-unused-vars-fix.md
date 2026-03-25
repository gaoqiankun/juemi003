# Web ESLint Hooks & Unused Vars Fix
Date / Status: 2026-03-25 / done / Commits:

## Goal
按任务要求修复前端 ESLint 中的 react-hooks 问题与 no-unused-vars 问题，并通过 lint/build 验收。

## Key Decisions
- 仅修改 `web/` 目录下与 ESLint 问题直接相关的文件。
- `no-explicit-any` 保持不处理，遵循任务范围。

## Changes
- `web/src/app/gen3d-provider.tsx`
  - 删除未使用的 `setGenerateStatus`
  - 调整 `refreshTaskListAction` 位置并补齐 `subscribeToTask` 依赖
  - `connectSse` 补齐 `applyTaskSnapshot` 依赖
  - `saveConfig` 补齐 `resetTaskState` 依赖
  - 初始化副作用拆分为「加载」与「卸载清理」两个 `useEffect`，补齐依赖并修复 cleanup 中 ref 读取告警
- `web/src/components/layout/user-shell.tsx`
  - 用 `languageMenuPathname` 替代路径切换时 effect 里同步 setState 的写法
- `web/src/components/task-thumbnail.tsx`
  - 用 `hasIntersected` + 派生 `isVisible` 替代 effect 同步 setState
  - 预览图重置/加载状态改为异步调度，避免 `set-state-in-effect`
- `web/src/components/three-viewer.tsx`
  - Viewer 初始化不再捕获可变 props，改由后续 effect 同步配置，清理 `exhaustive-deps`
- `web/src/components/ui/primitives.tsx`
  - 删除未使用的 `clsx` 与 `ButtonHTMLAttributes` import
- `web/src/lib/viewer.ts`
  - 删除未使用的 `size` 解构变量
- `web/src/pages/gallery-page.tsx`
  - 移除未使用的 `initialSelectedTaskId` 入参
- `web/src/pages/generate-page.tsx`
  - 模型选择改用 `effective*` 派生状态，清理 token 缺失分支中的 effect 同步 setState
- `web/src/pages/proof-shots-page.tsx`
  - 去除未使用参数 `_filter`
  - 抽离任务时间戳常量，修复 `react-hooks/purity`
  - 同步移除 `GalleryPage` 已废弃入参
- `web/src/pages/reference-compare-page.tsx`
  - 去除未使用参数 `_filter`
  - 抽离任务时间戳常量，修复 `react-hooks/purity`
  - 移除 effect 中同步 `setThumbnailUrl("")`
- `web/src/pages/viewer-page.tsx`
  - 订阅 effect 依赖从 `task?.status` 调整为 `task`

## Notes
- `cd web && npx eslint src --rule '{"react-hooks/exhaustive-deps": "error", "react-hooks/rules-of-hooks": "error"}'`：仅剩 `@typescript-eslint/no-explicit-any` 18 条
- `cd web && npm run lint`：仅剩 `@typescript-eslint/no-explicit-any` 18 条；`react-hooks/*` 与 `no-unused-vars` 均为 0
- `cd web && npm run build`：通过（零错误）
- `web/src/app/gen3d-provider.tsx` 仍 >500 行，本次属于 lint 修复范围，暂不做结构拆分
