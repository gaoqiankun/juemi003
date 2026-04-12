# 关键决策日志

> 记录影响调试和开发判断的重要行为变更，按时间倒序。
> AI Coder 完成任务后，若有影响其他模块行为的变更，在此追加一条。

---

## 2026-04-12

- **GPU 显存分配器启用 NVML 实时探针感知外部占用**：非 mock 模式的 `api/server.py` 在 `VRAMAllocator` 创建后注入 `engine/vram_probe.probe_device_free_mb`（基于 `pynvml` / NVML 驱动接口），allocator 的 `_effective_free_mb()` 现在以 `min(booked_free, nvml_actual_free)` 作为 `reserve()` 和 `_try_acquire_inference()` 的准入上限，能感知外部进程占用的显存而不再只看自己的账本。probe 采用懒加载 + init 失败永久缓存 + 线程锁保护，任何异常路径都降级到 booked_free，不会打断 allocator 决策。新增依赖 `nvidia-ml-py>=13.595.45`（用户显式授权），mock 模式完全跳过 probe 接入以保持纯内存行为。（plan: 2026-04-11-gpu-device-assignment.md）

- **同卡推理显存不足时启用 LRU 空闲模型卸载**：`api/server.py` 在 `ModelScheduler` 创建后注入 `vram_allocator.set_evict_callback(...)`，回调仅在同设备 `ready` 且无推理占用的模型里按 `ModelScheduler.get_last_used_tick()` 选择最久未使用项，调用 `ModelRegistry.unload()` 释放权重显存；卸载失败会记录 `vram_allocator.evict_failed` 并返回 False，回退到等待路径。（plan: 2026-04-11-gpu-device-assignment.md）

## 2026-04-11

- **模型加载改为按显存分配单卡启动 worker**：新增 `engine/vram_allocator.py`（`DeviceBudget` + `VRAMAllocator`）并接入 `api/server.py` 的 `runtime_loader`，加载时按 `weight_vram_mb` 选择单个 GPU，再把该 `device_id` 传给 `build_model_runtime(..., device_ids=(assigned_device,))`，不再为每个模型在所有 GPU 上各起一个 worker；卸载/加载失败会回收分配，避免后续模型被错误占用。（plan: 2026-04-11-gpu-device-assignment.md）

- **模型显存声明拆分为常驻权重与推理临时占用**：`storage/model_store.py` schema 增加 `weight_vram_mb` 与 `inference_vram_mb`（含迁移与 API 写入字段），`model/*/provider.py` 与 `model/base.py` 增加 `estimate_weight_vram_mb()` / `estimate_inference_vram_mb()`，`estimate_vram_mb()` 保持兼容输出总量；`engine/model_scheduler.py` 在估算可加载上限时优先使用 `weight_vram_mb`。（plan: 2026-04-11-gpu-device-assignment.md）

## 2026-03-30

- **模型运行时改为强依赖 dep_cache 就绪状态**：`api/server.py` 的 `build_model_runtime()` 在加载模型前会按 `model_dep_requirements -> dep_cache` 解析 `dep_paths`，任何依赖 `download_status != done`、`resolved_path` 为空或路径不存在都会直接抛 `ModelProviderConfigurationError`，避免运行时隐式联网或加载半成品依赖。（plan: 2026-03-30-weight-dep-b3.md）

- **离线兜底仅在 GPU 子进程启用**：`stages/gpu/worker.py` 在 `_build_process_provider()` 内设置 `HF_HUB_OFFLINE=1` 与 `TRANSFORMERS_OFFLINE=1`，主进程保持不设置，避免影响 `WeightManager` 与迁移脚本的依赖补齐流程。（plan: 2026-03-30-weight-dep-b3.md）

## 2026-03-26

- **GPU 子进程回传结果统一 CPU 化，避免 CUDA IPC 依赖**：`model/trellis2/provider.py` 在 `GenerationResult` 返回前递归将 tensor-like 值 `detach().cpu()`；`stages/gpu/worker.py` 新增 `_sanitize_generation_results_for_ipc()` 作为跨 provider 传输层兜底，确保 `multiprocessing.Queue` 不再裸传 CUDA tensor，规避容器内 `pidfd_getfd` 限制导致的 `rebuild_cuda_tensor/_new_shared_cuda` 失败。（plan: 2026-03-26-cuda-tensor-ipc-fix.md）

- **real + ProcessGPUWorker 模式主进程改为 metadata-only provider**：`api/server.py` 的 `build_provider()` 在 real 模式不再调用 `from_pretrained()`，改为构造各 provider 的 `metadata_only()` 实例；真实权重加载仅发生在 `stages/gpu/worker.py` 子进程 `_build_process_provider()`。主进程仍保留 `export_glb()`、`stages`、`estimate_vram_mb()` 能力，避免重复占用 GPU 显存。（plan: 2026-03-26-process-worker-main-process-metadata-provider.md）

- **HunYuan3D pipeline checkpoint 加载去外部目录依赖**：`model/hunyuan3d/pipeline/{shape,texture}.py` 改为在仓库内实现 checkpoint 解析与加载回退（`config.yaml + model(.variant).{safetensors|ckpt}`），不再依赖外部目录代码或 `model_index.json`；provider 调用方式保持不变。（plan: 2026-03-26-hunyuan3d-checkpoint-loading-no-external.md）

- **HunYuan3D pipeline 加载回退到上游 hy3dgen 语义**：`model/hunyuan3d/pipeline/{shape,texture}.py` 不再走 `diffusers.DiffusionPipeline.from_pretrained`（依赖 `model_index.json`），改为委托 `Hunyuan3D-2/hy3dgen/*/pipelines.py` 的 `from_pretrained`，恢复 `config.yaml + model(.fp16).safetensors/.ckpt` 的 checkpoint 加载路径。（plan: 2026-03-26-hunyuan3d-checkpoint-loading-fix.md）

- **Step1X-3D texture pipeline 恢复硬依赖 pytorch3d**：在 `docker/trellis2/Dockerfile` 显式安装 `pytorch3d` wheel，并回退 `model/step1x3d/provider.py` 的缺依赖降级逻辑，恢复 texture pipeline 原始加载语义（`ModuleNotFoundError` 仅在模块导入阶段被忽略，加载阶段失败仍报配置错误）。（plan: 2026-03-26-step1x3d-pytorch3d-docker-explicit-install.md）

## 2026-03-25

- **HunYuan3D real provider 改为仓库内 pipeline**：`model/hunyuan3d/provider.py` 不再运行时 import 外部 `hy3dgen`，统一切换为 `model/hunyuan3d/pipeline/{shape,texture}.py` 的自维护入口类；mock provider 与 BaseModelProvider 接口保持不变。（plan: 2026-03-25-hunyuan3d-pipeline-internalization.md）

## 2026-03-24

- **`wait_ready` 改为轮询**：模型未加载时不再立即 raise，改为轮询等待调度器触发加载。相关文件：`engine/model_registry.py`。（plan: 2026-03-24-model-registry-wait-ready-polling.md）

- **`on_model_loaded` 后补扫 pending 模型**：模型加载完成后自动触发一次 `_startup_scan_queued_models()`，避免"加载请求丢失"窗口。相关文件：`engine/model_scheduler.py`。（plan: 2026-03-24-model-scheduler-on-model-loaded-rescan.md）

## 2026-03-23

- **调度器启动扫描**：服务启动时自动扫描 QUEUED 任务并触发模型预热，不再需要手动触发。相关文件：`engine/model_scheduler.py`。（plan: 2026-03-23-scheduler-startup-scan.md）

- **模型路径从 DB 读取**：模型文件路径改为从 `model_definitions` 表读取，不再依赖 config.py 硬编码。相关文件：`storage/model_store.py`、`engine/model_registry.py`。（plan: 2026-03-23-model-path-from-db.md）
