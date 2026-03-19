# Generate Viewer 黑屏修复
Date / Status: 2026-03-19 / done / Commits: uncommitted

## Goal
调查并修复 `gen3d` Web UI 生成页在点击右侧最近生成列表中的已完成任务后，
中央 Three.js 查看器黑屏、不显示 3D 模型的问题，并补上 artifact 拉取失败时的可见错误反馈。

## Key Decisions
- 根因按部署链路处理，不把查看器继续直接绑定到 `artifact.url` 外链；生成页与详情弹窗统一走同源 `/v1/tasks/{id}/artifacts/{filename}` 代理下载
- 后端 artifact 下载接口对 `minio` backend 不再只支持本地文件路径，而是支持先从对象存储拉取到临时文件再回传浏览器
- 查看器加载失败时直接在查看器区域显示请求错误文案，避免用户只看到黑底完成态

## Changes
- 生成页与任务详情弹窗改为通过 `web/src/lib/task-artifacts.ts` 从任务信息构造同源 artifact 代理 URL，而不是直接使用 `rawArtifactUrl/resolvedArtifactUrl`
- `api/server.py` 的 `/v1/tasks/{task_id}/artifacts/{filename}` 改为走 `ArtifactStore.prepare_download()`，兼容 local/minio 两类 backend
- `storage/artifact_store.py` 新增对象存储下载到临时文件的准备逻辑，支持按 manifest 查找 artifact 并以正确 content type 返回
- `web/src/lib/viewer.ts` 在 GLB fetch / loader 失败时把错误详情显示到 overlay，例如 `模型文件请求失败：404 Not Found`
- `tests/test_api.py` 补了 minio backend 下“通过同源 proxy 下载 artifact”的回归覆盖

## Notes
- 本地浏览器实际验证入口使用 `http://127.0.0.1:18011/static/`；当前生产构建的 React `basename` 仍是 `/static`
- 浏览器实测结果：
- 同源 proxy 正常时，点击最近生成中的已完成任务后，主舞台能渲染可旋转的 3D 模型
- 把临时 artifact 文件移走制造 404 后，查看器区域会显示 `模型文件请求失败：404 Not Found`，不再静默黑屏
- 查看器 loading overlay 已细化为“请求模型 / 下载进度 / 解析模型结构 / 准备视图”等阶段，避免 Network 已返回 `200` 时页面仍只显示笼统的“正在下载模型…”
- 当前仓库回归结果为 `python -m pytest tests -q` -> `73 passed`
