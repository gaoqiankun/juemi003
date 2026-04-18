# 关键决策日志

> 记录影响调试和开发判断的重要行为变更，按时间倒序。
> AI Coder 完成任务后，若有影响其他模块行为的变更，在此追加一条。

---

## 2026-04-18

- **Inference allocation 生命周期从 ModelWorker 搬到 pipeline（设计中，代码待改）**：
  现象：生产观测到 gpu stage 结束 → export stage 启动的 ~1s 窗口内，admin 面板
  从 "推理 5.5 GB / 外部 0" 突变为 "推理 0 / 外部 4 GB"，直到 export 完才恢复。
  根因：`engine/model_worker.py` 的 `run_inference` 在 `finally` 里提前 release
  inference allocation，但 `run_batch` 返回的 mesh 仍是 CUDA tensor，export stage
  才 `.cpu()` 转换释放显存 —— 中间 ~1s 显存被占着但账本写 0，差值被 dashboard
  归为 "外部占用"。
  决策：inference allocation 是 **per-task 资源**（不是 per-run_batch 执行资源），
  生命周期覆盖 gpu + export 两个 GPU-bound stage。引入 `InferenceLease` context
  manager + `VRAMAllocator.reserve_for_task`，由 pipeline 协调层持有；
  ModelWorker 退出 allocation 管理职责，只保留 run_batch / 估算 / OOM bump
  target / 迁移物理执行。
  替代方案：mesh 同步 `.cpu()` 后再 release（已被 commit `c61a17a` 回滚，
  会触发 SIGBUS） · 忽略面板显示（与用户语义要求不符） · 延长 release 时机
  但留在 ModelWorker 内（反向耦合）—— 均否决。
  影响：`engine/vram_allocator.py`（加 Lease）、`engine/model_worker.py`（剥离
  allocation）、pipeline 协调层（接 lease + OOM 重试搬家）、`stages/gpu/scheduler.py`
  （删 `configure_inference_admission` 死代码）。weight allocation、`_do_migration`
  核心逻辑、Model Scheduler、前端面板均不动。
  （plan: `.ai/plan/2026-04-18-inference-lease-lifecycle.md` · 设计更新:
  `.ai/vram-management-design.md` §1、§2、§3.4–3.6、§11）

- **SSE 进度上报修复：pipeline stage_cb + heartbeat 可解析事件**（commit `d903d56`）：
  `model/trellis2/pipeline/pipelines/trellis2_image_to_3d.py` `run()` 加 `stage_cb`
  参数，四个 pipeline_type 分支（512/1024/1024_cascade/1536_cascade）均在
  sparse_structure / shape_slat / tex_slat 完成后触发回调。
  `model/trellis2/provider.py:_run_single` 移除前后包裹的 emit_stage，改用
  `stage_cb=emit_stage` 传入。
  `api/server.py` SSE heartbeat 从 `": heartbeat\n\n"` 改为 `"event: heartbeat\ndata: {}\n\n"`，
  并加 `X-Accel-Buffering: no` 响应头防 nginx 缓冲。
  `web/src/app/gen3d-provider/use-task-realtime.ts` 在 `applyEventPayload` 之前
  guard 掉 heartbeat 事件 —— 否则 `applyTaskSnapshot` 在 payload 缺 progress 时
  会 fallback 到 `defaultProgressForStatus(status)`，每次心跳都把进度回退到该
  状态默认值（gpu_material 90% → 82%）。clear watchdog 放在 guard 之前。
  生产验证：进度从"5% → 直接 100%"变成"5% → 25% → 60% → 90% → 95% → 100%"，
  SSE 不再因 watchdog 超时回退到 polling。
  （plan: `.ai/plan/2026-04-18-fix-progress-reporting.md`）

## 2026-04-13

- **GPUSlotScheduler 支持 shutdown，reload/unload 不再挂死 in-flight 请求**：`stages/gpu/scheduler.py` 新增 `SchedulerShutdownError` + `GPUSlotScheduler.shutdown()`；`acquire()` 改为 `asyncio.wait({queue.get, shutdown_event}, FIRST_COMPLETED)` 模式，shutdown 触发时立刻抛错，异常路径释放 `inference_allocation_id` 防止账本漏账。竞态保护：`_restore_slot_from_task` 在 shutdown 赢但 get 也拿到 device_id 时把 device 回填队列，避免 slot 永久消失。`release()` 在 shutdown 后 early return 不回填 queue。（plan: 2026-04-12-gpu-inflight-hang-fix.md）

- **ModelRegistry 新增 `"unloading"` 中间态消除 Phase 3 evict 的 TOCTOU**：`engine/model_registry.py` 的 `unload()` 开头立即 `entry.state = "unloading"`，`get_runtime()` 的既有 `state != "ready"` 判定自动拒绝即将死亡的 runtime。Phase 5 `reload()` 在 `await self.unload()` 之前先调 `old_runtime.scheduler.shutdown()`（`getattr + callable` 兜底），唤醒旧 scheduler 上所有 waiting tasks。（plan: 2026-04-12-gpu-inflight-hang-fix.md）

- **`ProcessGPUWorker.stop()` 统一 fail pending run_batch futures**：`stages/gpu/worker.py` 抽出 `_fail_pending(reason)` helper，`stop()` 在清 `_pending` 前对所有未完成 future `set_exception(ModelProviderExecutionError("gpu_run", "worker stopped"))`。`_fail_startup_and_pending` 同样复用。之前 `stop()` 只 `_pending.clear()` 不 cancel futures，导致 caller 的 `await future` 永久阻塞，现修复。（plan: 2026-04-12-gpu-inflight-hang-fix.md）

- **GPUStage retry 合并 `SchedulerShutdownError` 和 `ExternalVRAMOccupationTimeoutError`**：`stages/gpu/stage.py` `GPUStage.run` 的 retry 循环现在捕获两类异常，两者共享同一个 `migration_attempted` single-shot 守卫，加起来最多重试 1 次。`SchedulerShutdownError` 分支调 `wait_ready` 拿新 runtime（迁移已由其他 task 触发，本 task 只需等结果），不主动调 `reload`。（plan: 2026-04-12-gpu-inflight-hang-fix.md）

## 2026-04-12

- **GPU 模型支持跨卡迁移（Phase 5）**：`engine/vram_allocator.py` 新增 `ExternalVRAMOccupationTimeoutError(VRAMAllocatorError)` 子类，Phase 4c 的外部占用超时路径改抛这个子类。`stages/gpu/stage.py` 的 `GPUStage.run` 在 `scheduler.acquire()` 处包一层 `while True` + `migration_attempted` single-shot retry：捕获该子类后调 `ModelRegistry.reload(model, exclude_device_ids=(old_device,))`，刷新 runtime 后重试一次；第二次同类超时直接抛错（避免全集群不够时死循环）。非该子类的 `VRAMAllocatorError` 不触发迁移，沿用既有抛错语义。（plan: 2026-04-12-gpu-device-migration.md）

- **新增 `ModelRegistry.reload(model_name, *, exclude_device_ids)` API**：`engine/model_registry.py` 串行化同模型的并发 reload（`self._lock` 临界区 + `_ModelEntry.excluded_device_ids` 标记 + `wait_ready` 锁外等待），避免多个请求竞相 unload/load。内部复用 `unload` + 新建 entry + `_load_runtime` 路径；迁移失败自然走 `_load_runtime` 的 except 分支进入 `state="error"`，触发 `model_unloaded_listener` → `vram_allocator.release` 释放账本。`runtime_loader` 签名新增 `exclude_device_ids: Iterable[str] | None` 参数，`_call_runtime_loader` 用 `while True` 逐个 pop 不支持的 kwarg 做 TypeError 兼容降级（与现有 `device_id` 兼容 pattern 同构）。（plan: 2026-04-12-gpu-device-migration.md）

- **`VRAMAllocator.acquire_inference` 外部占用超时失败语义**：wait loop 新增 `_track_external_occupation_wait` 辅助方法，仅在 `effective_free < booked_free`（即 NVML probe 汇报低于账本）期间累积等待时间，超过 `external_vram_wait_timeout_seconds`（默认 30s）→ `raise VRAMAllocatorError("external VRAM occupation timeout ...")`。之前行为是永久 wait；现在上游调用者（`GPUSlotScheduler`、`stages/gpu/worker.py` 等）会收到该异常 propagation。内部争抢（同卡推理互相排队）不计时，由 Phase 3 的 evict 兜底；probe 为 None 时 `effective_free == booked_free`，永不触发 timeout 路径，降级到 Phase 3 行为。（plan: 2026-04-11-gpu-device-assignment.md）

- **新增持久化动态配置 `external_vram_wait_timeout_seconds`**：`storage/settings_store.py` 增加 `EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY`；`api/server.py` 在 startup 从 SettingsStore 读取并注入 allocator，GET `/api/admin/settings` 暴露 `externalVramWaitTimeoutSeconds` 字段，PATCH 校验 > 0 并 live apply 到 allocator，无需重启生效；同时把 `vram_allocator` 加入 `AppContainer` 便于 endpoint 访问。（plan: 2026-04-11-gpu-device-assignment.md）

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
