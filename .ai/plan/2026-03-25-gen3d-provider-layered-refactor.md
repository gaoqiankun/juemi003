# Gen3d Provider Layered Refactor
Date: 2026-03-25
Status: done

Date / Status: 2026-03-25 / done / Commits:
## Goal
按已确认分层，把 `web/src/app/gen3d-provider.tsx` 从单文件重构为目录化模块，保持对外 API 与行为不变。

## Key Decisions
- 严格按单向依赖：`task-record-utils -> use-task-store -> use-task-sync -> use-task-realtime`。
- `use-config-bootstrap` 与 `use-generate-workflow` 通过依赖注入接收回调，避免反向 import。
- 保持外部导入路径 `@/app/gen3d-provider` 不变。

## Changes
- 新建目录与模块：
  - `web/src/app/gen3d-provider/context.ts`
  - `web/src/app/gen3d-provider/state-persistence.ts`
  - `web/src/app/gen3d-provider/task-record-utils.ts`
  - `web/src/app/gen3d-provider/use-task-store.ts`
  - `web/src/app/gen3d-provider/use-task-sync.ts`
  - `web/src/app/gen3d-provider/use-task-realtime.ts`
  - `web/src/app/gen3d-provider/use-generate-workflow.ts`
  - `web/src/app/gen3d-provider/use-config-bootstrap.ts`
- `web/src/app/gen3d-provider.tsx` 重写为装配层（组合 state/sync/realtime/bootstrap/workflow 五层能力并组装 context value）。
- `@/app/gen3d-provider` 对外导出维持不变（`Gen3dProvider`、`useGen3d`、`Gen3dContext`、`Gen3dContextValue`、`canCancelTask`）。
- 去除了新拆分文件中新引入的 lint 问题（未使用变量、hook 规则、新增 `any`），保留项目已有 `viewer.ts` 中 `no-explicit-any` 存量。

## Notes
- 单文件规模：`web/src/app/gen3d-provider.tsx` 由 1265 行降到 212 行（`<= 250`）。
- 依赖方向符合约束：
  - `task-record-utils -> use-task-store -> use-task-sync -> use-task-realtime`
  - `use-config-bootstrap` / `use-generate-workflow` 通过 DI 接收回调，不反向 import 上层 hook。
  - 本地脚本静态检查结果：cycles = 0。
- 验收：
  - `cd web && npm run build` ✅
  - `cd web && npm run lint` ✅（仅剩 `web/src/lib/viewer.ts` 15 条 `@typescript-eslint/no-explicit-any` 存量）
