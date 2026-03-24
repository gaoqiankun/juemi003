# Generate 模型下拉去除 runtime_state UI
Date / Status: 2026-03-24 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）

## Goal
移除 Generate 页模型下拉中非 ready 状态的灰色标签/提示，仅按模型是否 enabled 过滤并展示模型名称。

## Key Decisions
- 前端模型选项归一化时仅处理 `enabled/is_enabled` 字段过滤，忽略 `runtime_state` 字段。
- 不调整后端 `/v1/models` 响应结构，本次只做用户侧展示逻辑收敛。
- 保留原有加载态/空态/失败态 placeholder 文案；仅去掉每个模型项的运行状态拼接文案与灰色样式。

## Changes
- `web/src/pages/generate-page.tsx`
  - 删除 `GenerateModelOption.runtimeState` 与 `normalizeRuntimeState()`。
  - `normalizeModelOptions()` 新增 `enabled/is_enabled` 过滤；`enabled === false` 的模型不进入下拉。
  - 下拉项渲染改为只输出 `model.displayName`，移除 runtime_state 相关 class 与 i18n 文案拼接。
- `web/src/lib/types.ts`
  - `UserModelPayload` 增加 `enabled?: boolean` 与 `is_enabled?: boolean`，匹配前端过滤字段。

## Notes
- 验证通过：`cd web && npm run build`（Node v24.14.0）成功。
- 本次未执行 git 提交；保留仓库内既有未提交变更不动。
