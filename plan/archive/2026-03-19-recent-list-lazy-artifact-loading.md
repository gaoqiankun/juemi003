# 最近生成列表按需加载模型
Date / Status: 2026-03-19 / done / Commits: uncommitted

## Goal
修正生成页“最近生成”列表的资源加载策略，避免列表刚出来就后台下载完整 `model.glb`，只在用户真正打开查看器时才请求模型文件。

## Key Decisions
- 最近生成列表不再通过前端 `renderModelThumbnail(...)` 从 GLB 生成缩略图
- 列表缩略图只继续使用已有的 `preview.png` artifact；若不存在，则显示占位态，不为此预下载整份模型
- 真正的 GLB 请求只保留在主舞台 `ThreeViewer` 与下载按钮链路上，避免列表阶段抢占带宽和解析 CPU

## Changes
- 删除 `web/src/app/gen3d-provider.tsx` 中针对 succeeded 任务的 `queueThumbnailGeneration(...)` 调用
- 移除 provider 内部基于 `renderModelThumbnail(...)` 的缩略图缓存、任务队列、请求头拼装逻辑
- 保留 artifact URL hydrate 逻辑，确保任务被选中后主舞台仍按原链路加载 `/v1/tasks/{id}/artifacts/{filename}`

## Notes
- 前端构建已通过：`npm run build`
- 这次改动只影响最近生成列表的预取行为，不改变查看器本身的加载、错误提示和交互逻辑
