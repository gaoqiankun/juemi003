# Web ESLint 工具接入
Date: 2026-03-25
Status: done

Date / Status: 2026-03-25 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
为 `web/` 接入 ESLint（Flat Config），启用 TypeScript 与 React Hooks 基础规则，并验证 lint/build 可运行。

## Key Decisions
- 使用 `eslint.config.js`（flat config）作为唯一 ESLint 配置入口。
- 启用 `@typescript-eslint` recommended 与 `react-hooks` recommended。
- 仅新增工具配置，不修改业务代码、不自动修复问题。

## Changes
- 已安装 dev 依赖：`eslint`、`@typescript-eslint/parser`、`@typescript-eslint/eslint-plugin`、`eslint-plugin-react-hooks`
- 已新增：`web/eslint.config.js`
  - flat config
  - 启用 `@typescript-eslint` recommended
  - 启用 `react-hooks` recommended
- 已修改：`web/package.json`
  - 新增脚本：`"lint": "eslint src"`
- 已执行：`cd web && npm run lint`（仅统计，不自动修复）
- 已执行：`cd web && npm run build`（零错误）

## Notes
- Lint 结果：总计 `45`（errors `37` / warnings `8`）。
- Top 5 规则：
  - `@typescript-eslint/no-explicit-any`：18
  - `@typescript-eslint/no-unused-vars`：9
  - `react-hooks/exhaustive-deps`：8
  - `react-hooks/purity`：6
  - `react-hooks/set-state-in-effect`：4
- 问题数未超过 50，本次未触发“存量问题暂不处理”标注条件。
