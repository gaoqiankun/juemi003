# E5 · Compose 补充 ADMIN_TOKEN 与 UPLOADS_DIR
Date / Status: 2026-03-15 / done / Commits: none

## Goal
让 `docker-compose.yml` 显式包含管理端点鉴权和上传目录的环境变量。

## Key Decisions
- 在 `hey3d-gen3d` 服务的 `environment` 中补 `ADMIN_TOKEN`
- 添加注释，说明 `ADMIN_TOKEN` 用于 `/admin/*` 管理端点认证
- 在同一处补 `UPLOADS_DIR=/data/uploads`

## Changes
| 文件 | 变更说明 |
|------|---------|
| `docker-compose.yml` | 新增 `ADMIN_TOKEN` 注释和变量；新增 `UPLOADS_DIR` |

## Notes
- 未运行自动化测试；本次仅修改 compose 环境变量配置
