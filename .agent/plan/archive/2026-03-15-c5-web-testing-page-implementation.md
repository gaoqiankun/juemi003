# C5 · Web 测试页实现
Date / Status: 2026-03-15 / done / Commits:

## Goal
在不修改任何现有文件的前提下，为 `gen3d` 新增一个纯静态浏览器测试页，覆盖连接配置、任务提交、SSE/轮询进度、GLB 结果展示和历史恢复。

## Key Decisions
- 只新增 `static/index.html`，不触碰现有 Python、配置、README 或已有 plan 文件
- SSE 使用 `fetch()` 读取 `text/event-stream`，因为 Bearer 鉴权下浏览器原生 `EventSource` 无法附带 `Authorization` header
- SSE 失败后自动降级到 `GET /v1/tasks/{id}` 的 3 秒轮询
- 历史记录和连接配置统一保存到 `localStorage`
- 对 `file://` artifact 做浏览器端候选 URL 探测；若仍不可访问，则明确提示需要同源代理或 MinIO presigned URL

## Changes
- `static/index.html`
  - 新增单文件测试页
  - 支持 API Base URL / Bearer Token 配置与保存
  - 支持图片 URL 与本地图片转 data URL 提交
  - 支持 callback URL
  - 支持 task history 恢复、SSE 回放、轮询降级
  - 支持 GLB 下载链接和 `<model-viewer>` 预览

## Notes
- 当前后端本地 artifact 仍可能返回 `file://`；若运行环境未额外挂出同源 HTTP 下载地址，页面会提示该限制
- 本次按硬约束仅新增文件，未修改任何既有实现
