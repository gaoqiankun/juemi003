# gen3d 真实链路首轮跑通记录
Date / Status: 2026-03-14 / done

## Goal

在 GPU 服务器上把 `gen3d` 的真实 TRELLIS2 链路从容器启动、模型加载、任务提交、推理执行、GLB 导出到 artifact 查询完整跑通，并记录本轮暴露出的运行时问题和修复方向。

## Key Decisions

- `flashattn` 基础镜像不再默认按脚本自动解析 GitHub release wheel；默认直接安装 `flash-attn`，只在显式指定 `FLASH_ATTN_INSTALL_TARGET` 时才使用 wheel / URL
- `flashattn` 基础镜像构建阶段加入 `FLASH_ATTENTION_FORCE_BUILD=TRUE`，并在镜像构建时直接执行 `import flash_attn`，避免产出 ABI 不兼容但表面构建成功的镜像
- `gen3d` 运行时依赖收口为 `transformers<5`，移除 `accelerate`，以避开 `briaai/RMBG-2.0` 被带入 meta tensor 初始化路径
- TRELLIS2 provider 调用改为对齐当前服务器上真实安装的 `Trellis2ImageTo3DPipeline.run()` 签名
- GLB 导出改为按 `MeshWithVoxel` 的真实返回结构调用模块级 `o_voxel.postprocess.to_glb(...)`

## Changes

- 修复 `docker/flashattn/` 构建链路
  - `build.sh` 默认使用 `flash-attn`
  - `Dockerfile` 强制本地 build 并在构建期校验 `import flash_attn`
- 修复 `gen3d` 运行时依赖
  - `docker/Dockerfile` 将 `transformers` 收口到 `<5`
  - `requirements-worker.txt` 移除 `accelerate`
- 修复 `model/trellis2/provider.py`
  - 支持基于 `resolution` 映射 `pipeline_type`
  - sampler 参数名改为 `shape_slat_sampler_params` / `tex_slat_sampler_params`
  - sampler nested 参数名改为 `guidance_strength`
  - 导出改为使用 `MeshWithVoxel` 字段喂给 `o_voxel.postprocess.to_glb(...)`
- 补充 `tests/test_api.py`
  - provider `run()` 参数映射单测
  - provider `export_glb()` 导出单测

## Notes

- 本轮真实任务已在服务器上跑通：
  - SSE 完整经过 `preprocessing -> gpu_queued -> gpu_ss -> gpu_shape -> gpu_material -> exporting -> uploading -> succeeded`
  - `GET /v1/tasks/{id}` 返回 `succeeded`
  - `GET /v1/tasks/{id}/artifacts` 返回本地 GLB artifact
  - 宿主机上已生成实际 `model.glb`
- 运行中暴露的主要问题依次为：
  - `flash_attn` ABI 不兼容
  - gated Hugging Face 依赖权限不足
  - `RMBG-2.0` 在 `transformers 5 + accelerate` 组合下走入 meta tensor 初始化路径
  - provider 调错 TRELLIS2 `run()` 参数签名
  - export 误把返回对象当成带 `o_voxel.postprocess.to_glb()` 的结构
- 当前 artifact 仍由 root 写入宿主机 bind mount；权限收口需后续单独处理
