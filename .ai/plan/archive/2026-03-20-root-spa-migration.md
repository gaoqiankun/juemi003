# 根路径 SPA 迁移
Date / Status: 2026-03-20 / done / Commits: n/a

## Goal
把 `gen3d` Web 前端从 `/static/` 迁移到根路径 `/`，让 FastAPI 直接以标准 SPA 方式服务 `web/dist`，同时避免 `/admin/*` 页面路由与后端管理 API 冲突。

## Key Decisions
- Vite `base` 改为 `/`，生产构建产物默认按根路径引用静态资源
- FastAPI 继续直接服务 `web/dist`，但挂载点改为 `/`，并对所有非 API 路径启用 `index.html` fallback
- 保留 `/static` 与 `/static/*` 的兼容重定向，避免旧链接立即失效
- 为避免与前端 `/admin/*` 冲突，后端管理 API 统一迁移到 `/api/admin/*`
- 对外新增 `/api/v1/*` 兼容入口，内部仍复用现有 `/v1/*` 处理逻辑

## Changes
- 更新 `web/vite.config.ts`，把 `base` 从 `/static/` 改为 `/`，并让 dev proxy 直接代理 `/api` 与 `/v1`
- 更新 `web/index.html` 与前端静态资源引用，去掉 `/static/` 前缀
- 更新 `api/server.py`：
  - 根路径 `/` 直接返回 `index.html`
  - `app.mount("/")` 服务 `web/dist`
  - 非 `/api/*`、`/v1/*`、健康检查与文档路径的客户端路由统一 fallback 到 `index.html`
  - `/static`、`/static/*` 改为 308 重定向到新的根路径路由
  - 管理 API 改为 `/api/admin/privileged-keys`、`/api/admin/keys`、`/api/admin/tasks`
  - 增加 `/api/v1/* -> /v1/*` 的兼容重写
- 更新 `tests/test_api.py`，覆盖新的根路径 SPA 行为、旧 `/static/*` 兼容跳转，以及 `/api/v1/tasks` 兼容入口
- 更新 `docs/PLAN.md`，同步管理 API 的真实路径前缀

## Notes
- 这次迁移后，前端页面入口以 `/generate`、`/generations`、`/admin/dashboard` 为准，不再依赖 `/static/*`
- 历史 plan 中关于 `/static/*` 和旧 `/admin/*` API 的记录保留为当时决策，不作为当前接口基线
