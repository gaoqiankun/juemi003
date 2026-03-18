# React Web UI 迁移
Date / Status: 2026-03-18 / done / Commits: uncommitted

## Goal
把 `gen3d` 原有的 vanilla JS Web UI 迁移到 `web/` 下的 React + TypeScript + Vite 项目，
保留现有 API 语义与任务流，先交付一个视觉专业、功能可用的基础版本。

## Key Decisions
- 采用 `Vite + React + TypeScript + React Router v6`，构建产物固定输出到 `web/dist/`
- 视觉层使用 `Tailwind CSS + shadcn 风格基础组件 + dark theme`，不引入额外设计框架
- 3D 预览继续使用 `Three.js`，但封装为 React 组件，不使用 `react-three-fiber`
- API 行为、鉴权方式、SSE 端点与任务状态机全部保持后端现有约定不变
- FastAPI 直接服务 `web/dist/`，并增加 SPA catch-all，支持 `/`、`/gallery`、`/settings`
- 对实时进度流增加“首个 SSE 事件超时降级轮询”兜底，避免浏览器流式事件迟迟不落地时前端界面卡在 processing

## Changes
- 新建 `web/` React 项目骨架，包含 Vite、TypeScript、Tailwind、组件封装与 `package-lock.json`
- 新建 `web/src/app/gen3d-provider.tsx`，统一管理配置、本地存储、任务列表、上传、建任务、SSE/轮询、缩略图与当前任务状态
- 新建三个页面：`web/src/pages/generate-page.tsx`、`web/src/pages/gallery-page.tsx`、`web/src/pages/settings-page.tsx`
- 新建 `web/src/components/three-viewer.tsx`、`web/src/lib/viewer.ts`，把 Three.js / GLTFLoader 预览逻辑迁移为 React 可复用组件
- 更新 `api/server.py`：静态资源挂载改为 `web/dist/`，`GET /` 返回 SPA `index.html`，未命中 API 的客户端路由回退到 `index.html`
- 更新 `docker/Dockerfile`：增加 Node builder stage，在镜像构建时执行 `npm ci` / `npm run build` 并复制 `web/dist/`
- 新增 `.dockerignore`，避免把 `web/node_modules`、`web/dist` 和本地验收工件打进 Docker context
- 删除旧 `static/` 目录，保留 `/static/*` URL 仅作为 React 构建产物的挂载前缀
- 更新 `.gitignore` 忽略 `web/node_modules/` 与 `web/dist/`
- 更新 `AGENTS.md`，补充 `web/` 的本地 build / dev 说明
- 更新 `tests/test_api.py`，覆盖 SPA 根路由、客户端路由回退、以及启用 dev proxy 时不转发前端路由

## Notes
- `npm run build` 通过；当前生产包主 JS 约 939 kB，Vite 会给出 chunk size warning，但不影响构建成功
- `python -m pytest tests -q` 当前结果为 `71 passed`，高于早期文档里的 67 基线
- 本地浏览器验收使用 `http://127.0.0.1:18001`，因为本机 `8000` 端口已被其他 Python 进程占用，未主动干预外部进程
- Playwright 冒烟验证覆盖：设置保存与 `/health` 绿点、生成页上传→processing→completed、Three.js 完成态、图库网格与详情侧栏
