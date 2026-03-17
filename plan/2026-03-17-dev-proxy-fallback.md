# 本地开发代理回源
Date / Status: 2026-03-17 / done / Commits: not committed

## Goal
为 `gen3d` 本地 FastAPI 服务增加一个仅开发态使用的透明代理：当设置 `DEV_PROXY_TARGET` 时，本地 `/static` 继续服务前端资源，其余请求回源到远端 gen3d 地址，从而避免浏览器跨域。

## Key Decisions
- 新增 `DEV_PROXY_TARGET` 配置项，未设置时完全关闭代理，保持现有行为不变
- 本地静态资源继续走 `FastAPI + StaticFiles`，只对非 `/static` 请求启用代理
- 代理逻辑使用 `httpx.AsyncClient`，保留原始 method、headers、body、query string，并透传上游状态码与响应头
- 为了让 `/ready`、`/v1/tasks` 这类已存在的本地路由也能回源，使用 HTTP middleware 做前置代理；同时在路由表末尾补一个 catch-all fallback，覆盖未知路径
- SSE/长连接兼容通过 `StreamingResponse` 透传上游字节流，避免把事件流读成一次性响应

## Changes
| 文件 | 变更 |
|------|------|
| `/Users/gqk/work/hey3d/gen3d/config.py` | 新增 `DEV_PROXY_TARGET` 环境变量配置与 URL 校验 |
| `/Users/gqk/work/hey3d/gen3d/api/server.py` | 增加 dev proxy client 生命周期、非 `/static` 请求代理、中转辅助函数、fallback catch-all |
| `/Users/gqk/work/hey3d/gen3d/tests/test_api.py` | 新增默认关闭与代理透传测试，并更新 mock GLB 下载断言 |
| `/Users/gqk/work/hey3d/gen3d/model/trellis2/provider.py` | 修复被中断的 mock GLB 导出，输出合法 GLB 供本地预览 |

## Notes
- 本地验收使用 `DEV_PROXY_TARGET=https://gen3d.frps.zhifouai.com python serve.py`
- 通过浏览器打开 `http://127.0.0.1:8000/static/index.html` 时无 CORS 报错；console 仅剩 Tailwind CDN 自带 warning
- `curl http://127.0.0.1:8000/ready` 已返回上游 `200 ready`，`curl http://127.0.0.1:8000/v1/tasks` 在未带 token 时返回上游 `401 invalid bearer token`，说明请求已实际回源
