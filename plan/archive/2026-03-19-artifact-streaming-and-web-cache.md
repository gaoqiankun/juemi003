# MinIO Artifact 流式下载与 Web 缓存
Date / Status: 2026-03-19 / done / Commits: uncommitted

## Goal
定位 gen3d Web UI 与 iOS 客户端在 MinIO backend 下加载 GLB 很慢的根因，并优先实现 server 端流式代理，补充低成本的 Web 端本地缓存。

## Key Decisions
- 根因确认在 server 代理下载路径：旧实现会先把 MinIO 对象完整下载到 `_staging/_downloads/...` 临时文件，再由 `FileResponse` 回给客户端，导致首字节必须等待整文件落盘
- 保留 local backend 现状不变，只在 `minio` backend 下新增 `get_object_stream` / `open_streaming_download` 路径，避免破坏本地文件直读语义
- boto3 `get_object()` 返回 `StreamingBody`，可用 `read()` 分块读取，因此不需要切 aiobotocore 也能先把流式代理做起来
- Web 端第一次加载速度靠 server 流式响应解决；后续重复查看再用 Cache API 持久化已下载 blob，并用 localStorage 记录响应 `etag`

## Changes
- `storage/artifact_store.py`
- 新增对象存储流式读取协议与 `ObjectStorageStreamResult` / `ArtifactStream`
- `Boto3ObjectStorageClient` 增加 `get_object_stream(...)`
- `ArtifactStore` 增加 `open_streaming_download(...)`，MinIO 模式下直接返回对象流、content-type、content-length、etag
- `api/server.py`
- `GET /v1/tasks/{task_id}/artifacts/{filename}` 在 MinIO 模式下改走 `StreamingResponse`
- 响应头补 `Content-Length`、`ETag`、`Content-Disposition`
- local backend 与 dev local model override 仍保持 `FileResponse`
- `web/src/lib/viewer.ts`
- 新增 Cache API 读取/写入逻辑；命中缓存时直接从本地 blob 恢复 viewer
- 记录 `etag` 到 localStorage，作为后续重新校验或排障的元数据
- `tests/test_pipeline.py`
- 新增 `open_streaming_download(...)` 覆盖，锁定 artifact store 能返回流式对象而非 staging 文件
- `tests/test_api.py`
- 现有 MinIO proxy 用例增加 `ETag` / `Content-Length` 断言
- 新增用例锁定下载路由不会再调用 `download_file()` 全量落盘

## Notes
- 本地完整回归：`python -m pytest tests -q` 通过，结果 `76 passed`
- 前端构建：`PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build` 通过
- 实际本地 MinIO + gen3d endpoint 的 curl 验证被环境阻塞：当前机器 Docker daemon 未启动，无法拉起 compose 里的 `minio` / `minio-init`
- 为了仍然量化收益，使用同一份 `ArtifactStore` 代码做了本地 benchmark server，对比旧 `prepare_download()` 缓冲路径与新 `open_streaming_download()` 流式路径，20 MB 假 GLB、每 1 MB 延迟 200 ms 条件下：
- 旧缓冲路径：`time_starttransfer=4.108668s`
- 新流式路径：`time_starttransfer=0.004099s`
- 总下载时间基本相同（约 `4.1s`），说明收益主要来自“客户端能立即开始接收”，而不是缩短总传输耗时
- iOS 端未改代码；现状是 `AssetStore.ensureLocalFile(...)` 只在应用私有目录做“文件是否已存在”的命中判断，首次下载仍完全依赖网络链路，后续建议把远端 `ETag` / `Last-Modified` 与本地文件元数据一起持久化，优先复用本地磁盘缓存并支持条件请求
