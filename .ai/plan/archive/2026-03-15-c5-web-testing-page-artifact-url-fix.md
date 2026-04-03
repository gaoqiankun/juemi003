# C5 · Web 测试页 artifact URL 拼接修复
Date / Status: 2026-03-15 / done / Commits:

## Goal
修复 `static/index.html` 在 local artifact backend 返回根相对路径时，无法基于 API Base URL 拼接出完整下载/预览地址的问题。

## Key Decisions
- 仅修改 `static/index.html`，不触碰任何 Python 代码
- 仅对以 `/` 开头的 artifact URL 做 API Base URL 补全
- 已是完整 `http(s)` URL 的 MinIO presigned URL 保持原样，不增加额外处理

## Changes
- `static/index.html`
  - 新增 artifact URL 归一化逻辑
  - 当 artifact URL 为 `/v1/tasks/{id}/artifacts/{filename}` 这类根相对路径时，自动拼接当前配置的 API Base URL
  - 下载链接和 `<model-viewer>` 预览统一使用补全后的完整 URL

## Notes
- `file://` artifact 仍沿用既有候选 URL 探测逻辑
- 本次修复兼容 local artifact 代理 URL 与 MinIO presigned URL 两种场景
