# VRAM 管理重构：三实体架构实现
Date: 2026-04-17
Status: done

## Goal

按 `.ai/vram-management-design.md` + `.ai/tmp/context-vram-redesign.md` 的设计，将显存管理重构为三实体架构（VRAM Allocator / Model Worker / Model Scheduler），实现 VRAM 中心化仲裁、OOM 自愈、推理侧迁移。

## Acceptance Criteria

- [ ] `engine/vram_allocator.py`：新增 `request_weight` / `release_weight` / `correct_weight` / `register_worker` / `unregister_worker`；`request_inference` 支持 5s 等待 + 迁移路径；持 `asyncio.Lock` 跨越 check→evict→record；外部基线校准（回路 3）
- [ ] `engine/model_worker.py`（新建）：`ModelWorker` 管理完整生命周期；三个状态标志（`_weight_allocated` / `_inference_busy` / `_evicting`）；OOM 自愈；物理迁移；`ModelWorkerInterface` Protocol
- [ ] `engine/model_registry.py`：改为 Model Worker 容器，协调 Worker 生命周期
- [ ] `engine/model_scheduler.py`：移除驱逐决策，只保留加载策略
- [ ] `stages/gpu/stage.py`：移除 `ExternalVRAMOccupationTimeoutError` 迁移逻辑
- [ ] `api/server.py`：删除 `_evict_idle_on_device`；移除旧 `reserve()` / `release()` 调用
- [ ] 保留不动：`stages/gpu/worker.py`、`stages/gpu/scheduler.py`
- [ ] pytest 全部通过（基线：216 passed）

## Tasks

### T1 — VRAMAllocator 扩展

文件：`engine/vram_allocator.py`

1. 新增类型：
   - `WeightAllocationID = NewType("WeightAllocationID", str)`
   - `InferenceAllocationID = NewType("InferenceAllocationID", str)`
   - `@dataclass WeightAllocation(allocation_id, device_id)`
   - `@dataclass InferenceAllocation(inference_allocation_id, weight_allocation_id | None, device_id)`
   - `VRAMInsufficientError(VRAMAllocatorError)`（所有设备都无法满足时抛出）

2. 新增 `ModelWorkerInterface` Protocol：
   ```python
   class ModelWorkerInterface(Protocol):
       async def evict(self) -> None: ...
   ```

3. `VRAMAllocator.__init__` 新增：
   - `self._worker_registry: dict[str, ModelWorkerInterface] = {}`（model_id → worker）
   - `self._weight_alloc_to_device: dict[str, str] = {}`（allocation_id → device_id）
   - `self._weight_alloc_to_model: dict[str, str] = {}`（allocation_id → model_id）
   - `self._weight_alloc_to_mb: dict[str, int] = {}`（allocation_id → mb）
   - `self._model_to_weight_alloc: dict[str, str] = {}`（model_id → allocation_id，1:1）
   - `self._lock = asyncio.Lock()`（新增，跨越 check→evict→record）
   - `self._next_weight_allocation_id = 1`
   - `self._external_baselines: dict[str, int] = {}`（device_id → mb，回路 3）
   - `self._probe_task: asyncio.Task | None = None`

4. 新增方法：
   - `async def request_weight(self, model_id, mb, exclude_device_ids=()) -> WeightAllocation`
     - 持 `_lock`，遍历设备（排除 exclude_device_ids）
     - 有空间 → 直接 book；不足但有 idle 候选 → 调用 worker.evict() 后 book；全 busy → 跳下一设备
     - 所有设备均失败 → raise VRAMInsufficientError
     - 返回 WeightAllocation
   - `def release_weight(self, allocation_id) -> None`（sync，无锁，仅改账本）
   - `def correct_weight(self, allocation_id, actual_mb) -> None`（sync，只升不降）
   - `def register_worker(self, model_id, worker) -> None`
   - `def unregister_worker(self, model_id) -> None`
   - 更新 `request_inference` → 新签名 `request_inference(model_id, device_id, inference_mb, weight_mb)`；持 `_lock`；5s 等待后迁移路径（在其他设备同时预订 weight + inference）；返回 `InferenceAllocation`

5. 新增内部方法：
   - `_idle_candidates_on(device_id, exclude_model_id)` → 从 `_worker_registry` 筛选符合驱逐候选条件的 Worker（见设计 §6）
   - `_safe_free_mb(device_id)` → 按设计 §4 账本公式计算（包含 external_baseline + safety_margin）
   - `async def _start_probe_loop(self) / _stop_probe_loop()`（回路 3，每 5s）

6. 旧接口：`reserve()` / `release()` / `acquire_inference()` 保留但标记为 `# deprecated`，内部委托到新方法（保证 T1 完成后原有测试仍通过）

### T2 — 新建 engine/model_worker.py

新建文件，包含：

1. `class ModelWorker`：
   - `__init__(model_id, allocator, gpu_worker_factory, db_store)`
   - 三个状态标志：`_weight_allocated / _inference_busy / _evicting`（`bool`，初始 False）
   - `weight_vram_mb: int`（从 DB 读历史值，无则用 provider 默认值）
   - `inference_vram_mb: int`（同上）
   - `_weight_allocation: WeightAllocation | None`
   - `_device_id: str | None`
   - `_gpu_worker: GPUWorkerHandle | None`

2. `async def load(self) -> None`
   - 调 `allocator.request_weight(model_id, weight_vram_mb)` → 得到 device_id
   - 调 `allocator.register_worker(model_id, self)`
   - 启动 GPU 子进程（在 device_id 上）
   - 子进程 ready → 读实测 weight_reserved_mb
   - 调 `allocator.correct_weight(allocation_id, actual_mb)`；更新自身 weight_vram_mb（只升不降）；持久化 DB
   - 设置 `_weight_allocated = True`

3. `async def evict(self) -> None`（实现 ModelWorkerInterface）
   - 设置 `_evicting = True`
   - 等待 `_inference_busy == False`（poll）
   - 停止 GPU 子进程
   - 调 `allocator.release_weight(allocation_id)`
   - 调 `allocator.unregister_worker(model_id)`
   - 设置 `_weight_allocated = False`、`_evicting = False`

4. `async def run_inference(self, batch, options, progress_cb) -> results`
   - 若 `_evicting` → raise（拒绝新推理）
   - 设置 `_inference_busy = True`
   - 调 `allocator.request_inference(model_id, device_id, inference_mb, weight_mb)`
   - 检查是否需要迁移（`weight_allocation_id is not None`）
     - 若需要迁移 → `_do_migration(new_device, new_weight_alloc, new_inference_alloc)`
   - 运行 `_gpu_worker.run_batch()`
   - 成功路径：更新 inference_vram_mb（EMA），调 `empty_cache()`，`release_inference()`，`_inference_busy = False`
   - OOM 路径：见 §3.5，重申请一次，失败则 raise

5. `async def _do_migration(self, new_device, new_weight_alloc, new_inference_alloc)`
   - 停旧子进程
   - `release_weight(old_weight_alloc)`
   - `unregister_worker` + `register_worker`
   - 在 new_device 启动新子进程
   - `correct_weight(new_weight_alloc, actual_mb)`

6. `async def unload(self) -> None`（主动卸载，复用 evict 路径）

### T3 — ModelRegistry 重构

文件：`engine/model_registry.py`

目标：改为 `ModelWorker` 容器，不再直接管理 GPU 子进程。

1. `_entries` 中的 `_ModelEntry.runtime` 改为持有 `ModelWorker` 引用
2. `load()` → 创建 `ModelWorker`，调用 `worker.load()`（异步 task）
3. `unload()` → 调用 `worker.evict()` / `worker.unload()`
4. `get_runtime()` → 仍返回 `ModelRuntime`（供 GPUStage 使用，内部从 Worker 中取 scheduler）
5. 移除直接操作 `GPUWorkerHandle` 的代码（由 Worker 管理）

### T4 — ModelScheduler 简化

文件：`engine/model_scheduler.py`

移除：
- `_select_eviction_candidate()` — 驱逐候选选择逻辑移入 VRAMAllocator
- `_evict_and_load()` — 不再由 Scheduler 执行驱逐
- `_enforce_loaded_slot_limit()` — VRAM Allocator 负责空间仲裁

保留：
- `request_load()` / `on_task_queued()` → 仅调用 `model_registry.load()`
- `on_task_completed()` → 更新 last_used tick、quota_exceeded
- `on_model_loaded()` → 重置 task counter

### T5 — GPUStage 简化

文件：`stages/gpu/stage.py`

移除：
- `ExternalVRAMOccupationTimeoutError` 捕获 + `model_registry.reload()` 迁移逻辑
- `migration_attempted` 标志

保留：
- `InternalVRAMContentionTimeoutError` 捕获（直接 raise）
- 基本的 slot acquire / run_batch / release 流程

### T6 — server.py 清理

文件：`api/server.py`

移除：
- `_evict_idle_on_device` 函数定义
- `vram_allocator.set_evict_callback(...)` 调用
- `vram_allocator.reserve(...)` 调用（移入 Worker）
- `model_registry.add_model_unloaded_listener(vram_allocator.release)` 注册
- `_on_weight_measured` listener（移入 Worker）

保留：
- `vram_allocator.set_metrics_hook(...)` — Prometheus 指标
- `vram_allocator.snapshot()` — Admin API 显示
- `vram_allocator.set_external/internal_vram_wait_timeout_seconds(...)` — 运行时配置

### T7 — 测试更新

- 更新 `tests/test_vram_allocator.py`：新增对 `request_weight` / `release_weight` / `correct_weight` / `register_worker` / `request_inference`（迁移路径）的测试
- 更新 `tests/test_model_registry.py`：适配新 Worker 容器结构
- 更新 `tests/test_gpu_stage_migration.py`：移除旧迁移场景，改为 Worker 迁移场景
- 更新 `tests/test_model_scheduler.py`：移除驱逐相关用例
- 新增 `tests/test_model_worker.py`：OOM 自愈、evict 流程、迁移

## 实施顺序

T1 → T2 → T3 → T4 → T5 → T6 → T7（串行，前置依赖后置）

## 参考

- `.ai/vram-management-design.md` — 所有接口定义、流程图、账本公式
- `.ai/tmp/context-vram-redesign.md` — 设计决策与实施范围

## Summary

完整实现三实体 VRAM 管理架构。VRAMAllocator 扩展为账本+仲裁中心，ModelWorker（新建）管理模型完整生命周期并持有三状态标志，ModelScheduler 简化为纯加载策略层。OOM 自愈、推理侧迁移、外部基线校准（回路 3）全部落地。测试 207 passed。

## Key Decisions

- asyncio.Lock 持锁覆盖整个 check→evict→record 循环（含 sleep 窗口），防止并发双重驱逐
- _inference_busy 在 OOM 重申请窗口保持 True，防止被误选为驱逐候选
- register_worker 在 request_weight 成功后才调用（未持有 allocation 的 Worker 不进驱逐候选池）
- Mock 运行时强制 inference_vram_mb=1，避免测试中触发 5s 等待
- _clamp_inference_estimate_mb 保留为 re-export（加 noqa: F401），测试文件从 server 模块导入它

## Changes

- `engine/vram_allocator.py`：新增 request_weight / release_weight / correct_weight / register_worker / unregister_worker；request_inference 增加等待+迁移预订路径；asyncio.Lock；外部基线校准 probe loop；新类型 WeightAllocation / InferenceAllocation / VRAMInsufficientError / ModelWorkerInterface
- `engine/model_worker.py`（新建）：ModelWorker 完整实现，含 load / evict / unload / run_inference / _do_migration / OOM 自愈；_ModelWorkerSchedulerAdapter 适配 GPUStage 的 scheduler.acquire() 调用路径
- `engine/model_registry.py`：改为 Worker 容器；_CompatRuntimeWorker 适配老式工厂返回的 ModelRuntime
- `engine/model_scheduler.py`：移除驱逐决策，只保留加载策略与配额统计
- `stages/gpu/stage.py`：移除 ExternalVRAMOccupationTimeoutError 迁移逻辑
- `api/server.py`：删除 _evict_idle_on_device；移除旧 reserve/release/weight-measured listener 注入；改用 ModelWorker 工厂

## Notes

- stages/gpu/worker.py 和 stages/gpu/scheduler.py 未修改
- 旧接口 reserve() / release() / acquire_inference() 保留为 deprecated wrappers，委托到新账本路径
