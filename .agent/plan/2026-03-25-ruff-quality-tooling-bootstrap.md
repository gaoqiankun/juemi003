# Ruff 代码质量工具接入
Date / Status: 2026-03-25 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）

## Goal
为后端项目接入 Ruff 静态分析基础配置，确保可执行 `ruff check .` 并产出当前问题统计。

## Key Decisions
- 在 `requirements.txt` 末尾追加 `ruff` 依赖。
- 新增项目根 `ruff.toml`，启用 E/W/F/I/C90 规则并设置复杂度上限为 10。
- 按要求排除 `.venv/` 与 `Hunyuan3D-2/`。

## Changes
- 已修改：`requirements.txt`（末尾追加 `ruff>=0.11,<1.0`）
- 已新增：`ruff.toml`
  - `select = ["E", "W", "F", "I", "C90"]`
  - `max-complexity = 10`
  - `exclude = [".venv", "Hunyuan3D-2"]`
- 已执行：`.venv/bin/ruff check .` 与 `.venv/bin/ruff check . --statistics`

## Notes
- Ruff 扫描结果：`297` 条问题。
- 主要类型（按数量）：`E501=224`、`E402=39`、`I001=19`、`C901=8`、`F821=3`。
- 问题数超过 50：**存量问题暂不处理，后续逐步清理**。
- 本任务未修改任何业务代码，未引入新增（非存量）业务问题。
