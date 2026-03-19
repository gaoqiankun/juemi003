# E15-A：后端生成 preview.png 缩略图
Date: 2026-03-19
Status: done

## Goal
Pipeline 完成后自动渲染一张 512×512 preview.png 存为 artifact，让图库和历史面板显示真实缩略图而非占位图；同时把用户原始输入图保存为 artifact input.png，方便后续使用与展示。

## Key Decisions
- 渲染库：trimesh + pyrender（EGL headless），加入 requirements-worker.txt；Dockerfile 确认/补充 libegl1-mesa
- 相机：固定正前方（azimuth=0, elevation=20°），依赖 Trellis2 canonical alignment；距离根据 bounding sphere 自动计算
- 背景：#2a2a2a（与 Web viewer 一致）；3 点灯光（key + fill + rim）
- 插入位置：最终 export stage 写完 GLB 后执行 render_preview；preprocess stage 最开始保存 input.png
- 容错：render_preview 用 try/except 包住，失败只写 warning log，不把任务打到 failed
- artifact 存储：走现有 artifact_store 接口，文件名 preview.png / input.png

## Changes
- `PreprocessStage` 注入 `artifact_store`，在读取原始输入后立即把原始字节保存为 artifact `input.png`，并在 local 下载路径优先使用 manifest 里的 `content_type`，因此 `input.png` 即使承载 JPEG 原始字节也会回正确 MIME
- `ExportStage` 在 GLB 导出后追加 preview 渲染链路，生成 `preview.png` 并与 `model.glb` / `input.png` 一起回写完整 manifest；最终 artifact 顺序固定为 `model.glb`、`preview.png`、`input.png`
- 真实渲染逻辑拆到 `stages/export/preview_renderer.py`，由 `ExportStage` 通过独立子进程调用 `trimesh + pyrender`，避免 OpenGL/EGL 异常直接带崩主服务；preview 渲染或发布失败只记 warning，不影响任务最终 `completed`
- `ExportStage._render_preview_png()` 的子进程超时从 3 秒上调到 60 秒，兼容 EGL headless 首次驱动初始化开销；pipeline 主路径和后续复用该方法的补救渲染路径保持一致
- `requirements.txt` / `requirements-worker.txt` 新增 `trimesh`、`pyrender`，`docker/Dockerfile` 补 `libegl1-mesa`
- API 展示层继续保持“只有 succeeded 任务对外暴露 artifacts”语义，避免失败任务因为提前落盘 `input.png` 而改变现有接口行为
- 新增测试覆盖：
  - mock pipeline 成功时产出 `input.png` 与合法 PNG `preview.png`
  - preview 渲染抛错时任务仍保持 `succeeded`
  - API 成功任务可直接 GET `/v1/tasks/{id}/artifacts/preview.png` 和 `/input.png`

## Notes
- 前端 task-thumbnail.tsx 已预留 /v1/tasks/{id}/artifacts/preview.png，404 时 fallback 占位图，后端落地后自动生效
- 当前全量回归结果：`gen3d/.venv/bin/python -m pytest gen3d/tests -q` -> `79 passed`
- 当前 macOS 本机的真实 `pyrender`/OpenGL 路径不适合作为稳定验收基线，因此生产代码已把 preview 渲染隔离到子进程；API 级本地验收由新增测试 `test_create_task_serves_preview_and_input_artifacts` 覆盖，Linux/EGL 运行时则由 Dockerfile 补齐 `libegl1-mesa`
