# 用户 Setup 配置与真实请求链路对齐
Date / Status: 2026-03-21 / done / Commits: not committed in this session

## Goal
检查并修正用户侧 `generate-page.tsx` 最近生成面板、任务列表请求、Setup 保存配置、图片上传与任务提交之间的真实 API 链路，消除 mock 配置与 provider 配置分叉导致的“已配置但请求没带上”的问题。

## Key Decisions

- `generate-page.tsx` 继续以 `useGen3d()` 为唯一真实数据源，不回退到 `use-generate-data.ts`
- Setup 页面不再单独写 `app-api-key` / `app-server-url` 后跳转，而是直接调用 `useGen3d().saveConfig()`，让内存态、localStorage、后台健康检查与任务列表刷新保持一致
- `user-config.ts` 改为优先读取 `app.react.config.v1`，旧的 `app-api-key` / `app-server-url` 仅作为 legacy fallback
- 路由守卫同时兼容 provider 当前状态与已落盘配置，避免 Setup 保存后在一次导航内被旧状态误判回 `/setup`

## Changes

- `web/src/pages/setup-page.tsx`
  - 移除 `use-setup-data` mock hook
  - 改为读取 `useGen3d()` 的 `config` 作为初始值
  - 保存时调用 `saveConfig({ token, baseUrl })`，不再手写独立 localStorage
- `web/src/components/guards/protected-user-route.tsx`
  - 改为使用 provider 当前 `config.token`，并兼容 `hasUserApiKey()` 的落盘值检查
- `web/src/lib/user-config.ts`
  - 优先从 `app.react.config.v1` 读取 `token/baseUrl`
  - 保存时同步写入 canonical JSON 和 legacy keys
- `web/src/app/gen3d-provider.tsx`
  - 启动读取配置时兼容 legacy setup keys，避免已有本地配置失效

## Notes

- 任务列表真实请求仍为 `GET /v1/tasks?limit=20&before=<cursor>`，鉴权头为 `Authorization: Bearer <token>`
- 图片上传真实请求仍为 `POST /v1/upload`（multipart `file`），任务提交真实请求仍为 `POST /v1/tasks`
- 提交任务成功后仍会执行一次静默 `refreshTaskList(...)`，随后对新任务开启 SSE / polling 订阅
- 验证：`cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
