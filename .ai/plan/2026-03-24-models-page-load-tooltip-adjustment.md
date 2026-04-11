# 模型列表加载按钮与错误提示展示调整
Date: 2026-03-24
Status: done

Date / Status: 2026-03-24 / done / Commits: N/A（按 AGENTS.md，本轮不执行 commit）
## Goal
调整 Admin 模型列表两处交互：  
1) 加载按钮仅在 `not_loaded/error` 状态显示；`loading/ready` 状态不显示。  
2) `error` 状态的错误信息从行内文本改为 hover 提示，保持运行状态单元格高度与其他行一致。

## Key Decisions
- 当前项目未提供可复用 Tooltip 组件，采用 `title` 属性作为兜底 tooltip。
- 保留 `error` Badge 显示，仅移除错误文本段落，避免错误行高度被撑高。
- 加载按钮展示逻辑严格按 runtime_state 控制；按钮保留 `isBusy` 防重复点击禁用。

## Changes
- `/Users/gqk/work/hey3d/gen3d/web/src/pages/models-page.tsx`
  - 新增 `shouldShowLoadAction`：仅 `not_loaded/error` 时渲染加载按钮。
  - `loading/ready` 状态不再渲染加载按钮。
  - 运行状态列移除 error message 段落，不再直接渲染错误文本。
  - `error` 且存在 `errorMessage` 时，将错误内容写入 Badge 的 `title`，并加 `cursor-help` 提示可悬停查看。

## Notes
- 验证通过：  
  `cd /Users/gqk/work/hey3d/gen3d/web && export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" && npm run build`
- 构建日志中有本地环境提示 `pyenv: cannot rehash ... isn't writable`，不影响构建结果。
