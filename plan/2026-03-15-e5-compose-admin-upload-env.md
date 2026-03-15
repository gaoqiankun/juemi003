# E5 · 补充 ADMIN_TOKEN 配置
Date / Status: 2026-03-15 / planning

## Goal
确保部署时用户能在 `.env.example` 中看到 `ADMIN_TOKEN`，知道需要配置它。

## Key Decisions
- `docker-compose.yml` 补 `ADMIN_TOKEN`（支持 `.env` 覆盖）和 `UPLOADS_DIR`（容器内固定路径）
- `deploy.sh` 的 heredoc 补 `ADMIN_TOKEN=`，紧跟 `API_TOKEN` 之后
- `UPLOADS_DIR` 不放进 `.env.example`，容器内路径固定，用户无需配置

## Changes
| 文件 | 变更说明 |
|------|---------|
| `docker-compose.yml` | 新增 `ADMIN_TOKEN` 和 `UPLOADS_DIR`（已完成）|
| `deploy.sh` | heredoc 补 `ADMIN_TOKEN=`（待完成）|

## Notes
- `UPLOADS_DIR` 在 docker-compose.yml 里硬编码为 `/data/uploads`，宿主机路径由 volume 挂载的 `GEN3D_DATA_DIR` 控制，用户不需要单独配置
