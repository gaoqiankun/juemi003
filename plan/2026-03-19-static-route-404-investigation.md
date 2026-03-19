# /static 404 排查
Date / Status: 2026-03-19 / done / Commits: n/a

## Goal
调查 `gen3d` Web UI 直接访问 `/static` 返回 404 的原因，确认当前仓库是否仍缺少 SPA 路由兜底，并给出可执行修复结论。

## Key Decisions
- 以当前 `main` 分支代码为准检查 `api/server.py`，重点确认 `/static`、`/static/` 和 `/static/*` 的实际路由行为
- 不占用本机已被其他项目使用的 `8000` 端口；改用远端域名与临时本地端口交叉验证，避免误把别的服务的 404 当成 `gen3d` 缺陷
- 若当前仓库代码已包含修复，则不再重复改动路由逻辑，只记录“部署版本落后于仓库 HEAD”的结论

## Changes
- 读取 `gen3d/AGENTS.md`、`docs/PLAN.md` 以及相关 plan，确认 React Web UI 的 `/static` SPA fallback 已在 2026-03-18 和 2026-03-19 两轮变更中落地
- 远端验证：
  - `GET https://gen3d.frps.zhifouai.com/` 返回当前 `gen3d Studio` `index.html`
  - `GET https://gen3d.frps.zhifouai.com/static` 返回 `404 {"detail":"not found"}`
  - `GET https://gen3d.frps.zhifouai.com/static/` 与 `GET /static/gallery` 返回 `404 {"detail":"Not Found"}`
  - `HEAD https://gen3d.frps.zhifouai.com/static/assets/index-C4-XWido.js` 返回 `200`
- 代码核对：
  - `api/server.py` 当前已包含 `@app.get("/static") -> 308 /static/`
  - `api/server.py` 当前已包含 `@app.get("/static/") -> index.html`
  - `SPAStaticFiles` 当前已为 `/static/*` 客户端路由提供 `index.html` fallback，同时保留真实资源文件直出
- 本地验证：
  - 本机 `8000` 端口实际是另一套 `uvicorn app.main:app --reload` 服务，不是 `gen3d`
  - 临时在 `19180` 启动当前 checkout 后，`GET /static -> 308`，`GET /static/ -> 200 + HTML`，`GET /static/gallery -> 200 + HTML`，`HEAD /static/favicon.svg -> 200`
- 回归验证：`python -m pytest tests -q` 结果为 `74 passed`

## Notes
- 远端 404 响应模式与仓库旧实现一致，说明线上/生产实例尚未部署包含 `0b6f1f2` 的新版本
- 当前仓库无需再重复修改 `/static` 路由逻辑；要让 `https://gen3d.frps.zhifouai.com/static` 正常打开，需要把现有 `main` 或至少包含 `0b6f1f2` 的镜像重新部署到实际服务
- 本次排查未发现 frp 对路径做 `/static -> /` 一类重写；远端 `/static/assets/*` 仍能命中，问题核心仍是后端运行版本未带 SPA fallback
