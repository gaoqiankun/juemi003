# E6 · 抽离 deploy .env.example 模板
Date / Status: 2026-03-16 / done / Commits: uncommitted

## Goal
把 `deploy.sh` 内嵌的 `.env.example` heredoc 抽成仓库根目录的独立文件，避免模板重复和维护漂移。

## Key Decisions
- 根目录新增 `.env.example`，内容保持与原 heredoc 一致
- `ADMIN_TOKEN` 仍紧跟在 `API_TOKEN` 之后
- `deploy.sh` 不再内联写模板，改为直接复制根目录 `.env.example`

## Changes
- `.env.example`
  - 新增部署模板，保留原 heredoc 的全部变量
- `deploy.sh`
  - 删除 `.env.example` heredoc
  - 改为 `cp "$ROOT_DIR/.env.example" "$STAGE_DIR/.env.example"`

## Notes
- 验证命令：`./deploy.sh --no-build`
