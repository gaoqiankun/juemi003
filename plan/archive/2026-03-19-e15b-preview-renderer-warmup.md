# E15-B：preview 渲染器常驻预热
Date: 2026-03-19
Status: done

## Goal
消除每次渲染都要冷启动 EGL 的开销（约 3-5s），把实际渲染耗时降到 <1s。

## Key Decisions
- 改为常驻渲染子进程：服务启动时 spawn 一个长期存活的 renderer 进程，EGL context 初始化一次后复用
- 通信方式：stdin/stdout 传递请求和响应（GLB 路径进，PNG bytes 出），简单可靠
- 启动预热：子进程起来后立即渲染一帧 dummy mesh（小立方体），确认 EGL 可用、context 已热身
- 崩溃重启：render 请求发现子进程已死则自动重启，重启后重新预热，再执行本次渲染
- 子进程超时：单次渲染保留合理超时（如 30s），冷启动超时可放宽到 60s（首次 or 重启后）
- 影响范围：pipeline 路径和 on-demand 路径共用同一个常驻进程实例

## Changes
- 新增 `stages/export/preview_renderer_service.py`：封装单例常驻 preview renderer 子进程，统一处理启动预热、请求收发、崩溃重启、超时和优雅退出
- 新增 `stages/export/preview_protocol.py`：定义 stdin/stdout 长度前缀协议，承载 JSON header + binary body
- 改造 `stages/export/preview_renderer.py`：增加 `--serve` 常驻模式，进程内持有 `pyrender.OffscreenRenderer`，启动后先 warmup dummy mesh，再处理 path/bytes 渲染请求
- 改造 `stages/export/stage.py`：pipeline export 路径不再直接 spawn subprocess，统一走 `PreviewRendererService`
- 改造 `api/server.py`：FastAPI lifespan 启动/停止共享 renderer service；on-demand preview 补救渲染也复用同一实例
- 更新 preview 相关测试：pipeline/API 改为 mock `PreviewRendererService`；新增 service 崩溃后自动重试成功、启动预热失败不阻塞服务启动的覆盖
- 验收：`python -m pytest tests -q` 通过，结果为 `85 passed`

## Notes
- 不改变 artifact_store 写入逻辑和 API 语义
- 原 subprocess-per-render 的超时常量可以保留用于重启后首次渲染超时
- 测试：mock 常驻进程，验证 pipeline 和 on-demand 路径都走同一渲染实例
