# Inference Allocation 生命周期重构:Per-task Lease
Date: 2026-04-18
Status: done

## Summary

把 inference allocation 生命周期从 ModelWorker 执行级搬到 pipeline 任务级。
新增 `InferenceLease` async context manager 和 `VRAMAllocator.reserve_for_task`,
由 `PipelineCoordinator` 在协调 gpu + export 两个 GPU-bound stage 时持有 lease,
覆盖整个 GPU 显存占用窗口。OOM 自愈逻辑搬到 pipeline 层用 `lease.bump_and_retry_once`。
ModelWorker 退出 allocation 管理职责,改为暴露 `estimate_inference_mb` /
`resolve_oom_bump_target_mb` / `apply_inference_allocation` /
`apply_successful_inference_measurement` / `begin_task_inference` /
`end_task_inference` / `empty_cuda_cache` 等 public 工具方法供 pipeline 调度。
`stages/gpu/scheduler.py` 死代码 (`configure_inference_admission` 及相关字段) 一并清理。

## Key Decisions

- **per-task 资源**: inference allocation 生命周期 = task 生命周期,不是 run_batch 调用周期
- **InferenceLease as context manager**: `__aexit__` 始终释放,异常路径自动清理
- **OOM 重试搬到 pipeline**: 通过 `lease.bump_and_retry_once(new_mb)` 原地换 allocation,
  不复用 ModelWorker 内部的 finally release 模式
- **`_inference_busy` 改为持有计数器** (`_inference_busy_holds`): begin/end_task_inference
  与 run_batch 都增减,eviction 等待 hold 全部释放
- **保留 `run_inference` alias**: 临时向后兼容,内部 caller 已切到 `run_batch`
- **不动 SIGBUS 约束**: 沿用 `_worker_process_main` 的 `del + gc.collect + empty_cache` 模式

## Changes

### 新增
- `engine/vram_allocator.py`: `InferenceLease` 类 + `VRAMAllocator.reserve_for_task(...)` 方法
- `tests/inference_lease_test_utils.py`: 共享 fixture (TrackingVRAMAllocator / FakeRegistry / Lease GPU/Export stages)
- `tests/test_inference_lease_pipeline.py`: 三个集成测试 (lease 跨 gpu+export / OOM 自愈 / export 异常释放)

### 修改
- `engine/pipeline.py`: `PipelineCoordinator` 加 `inference_allocator` + `model_registry` 参数,
  `_run_gpu_export_with_lease` / `_run_gpu_with_oom_retry` 接管 lease 协调与 OOM 重试,
  `_looks_like_oom` 从 model_worker 搬到这里
- `engine/model_worker.py`: 剥离 `run_inference` 的 allocation 管理(改为 `run_batch` + 5 个 public 方法);
  `_inference_busy` 改 `_inference_busy_holds` 计数器;`_apply_successful_inference_measurement`
  + `_resolve_oom_bump_target_mb` 改 public
- `engine/model_registry.py`: 新增 `get_worker(model_name) -> ModelWorker | None`
- `api/server.py`: `PipelineCoordinator` 实例化时传入 `inference_allocator` + `model_registry`
- `stages/gpu/scheduler.py`: 删 `configure_inference_admission` / `_acquire_inference_allocation`
  及 `_inference_allocator` / `_inference_model_name` / `_inference_device_id` /
  `_estimate_inference_vram_mb` / `_inference_allocations_by_device` 五个字段
- `model/trellis2/provider.py`: `_run_single` 仅在 `emit_stage` 非 None 时传 `stage_cb` kwarg
  (修 test_api 已有断言,Worker 标记为 unblock fix)
- `tests/test_model_worker.py`: 调整签名,覆盖新 public API + lease-via-pipeline 迁移流
- `tests/test_vram_allocator.py`: 新增 lease 测试 (正常释放 / 异常释放 / bump 后 allocation id 改变)

### 文档(Orchestrator 之前预写)
- `docs/vram-management.md` 新建(455 行,人类向 VRAM 管理说明)
- `.ai/vram-management-design.md` §1 / §2 / §3.4–3.6 / §11 修订(VRAMAllocator 接口 + Lease 决策章节)
- `.ai/decisions.md` 追加 2026-04-18 条目(本次 + 前置 d903d56 SSE 进度修复)

## Notes

- 213 tests 全部通过(包含 8 个新增 lease 相关测试)
- Task 7 (生产验证 admin 面板「推理 > 0, 外部 = 0」) 未在本次 commit 内完成,
  待部署后由用户验证;若复现成功,可在后续 memo / 新 plan 里勾选 AC 最后一条
- `run_inference` alias 保留待下一轮清理;搜全仓内部 caller 已无,仅需观察一两次
  上线后无外部依赖即可删除

## Goal

修复 inference allocation 生命周期与 GPU 显存实际占用时段错位的问题。

**现状**: `ModelWorker.run_inference` 在 `_run_batch` 结束后立即 `release_inference`。
但 `run_batch` 返回的 mesh 还停留在 CUDA 上,export 阶段才把它 `.cpu()` 转出去。
这段时间(本次观测 ~1s)显存账本写"推理=0",面板把这 4 GB 归为"外部占用"。

**期望**: 推理前申请足够显存 → GPU 负载全程(包括 export)都显示为推理占用 →
所有 GPU 负载结束才释放。

**根因**: Inference allocation 本质是**任务级资源**(绑 request sequence 生命周期),
但实现里被 ModelWorker 当成**执行级资源**(绑 run_batch 调用)。语义不匹配。

## Acceptance Criteria

- [ ] `ModelWorker.run_inference` 不再调用 `request_inference` / `release_inference`
- [ ] `ModelWorker` 暴露 `estimate_inference_mb(options: dict) -> int` 查询估算
- [ ] Pipeline 层(或 GPU stage 的调用方)通过 `allocator.reserve_for_task(...)`
  context manager 持有 lease,lease 覆盖 `gpu stage` + `export stage` 两个阶段
- [ ] OOM 重试逻辑搬到 lease 对象里,暴露 `lease.bump_and_retry_once()` 供上层调用
- [ ] `stages/gpu/scheduler.py` 的死代码(`configure_inference_admission` 及
  `_acquire_inference_allocation` 未被配置时返回 None 的分支)清理
- [ ] 现有 207 tests 全部通过(或调整到新签名通过)
- [ ] 新增集成测试:一个完整任务中 `used_inference_vram_mb > 0` 覆盖 gpu + export 全程
- [ ] 新增回归测试:OOM 场景下 lease 正确释放旧 allocation → 申请新 allocation → 重试
- [ ] `.ai/vram-management-design.md` 更新第 2~3 节,明确 inference allocation 的
  拥有者是 pipeline / GPU 任务协调层,不是 ModelWorker
- [ ] `.ai/decisions.md` 追加一条决策记录(日期、动机、替代方案、结论)
- [ ] 生产复现:完整任务期间 admin 面板始终显示 `推理 > 0, 外部占用 = 0`

## Out of Scope

- Weight allocation 生命周期不动(仍由 ModelWorker 管)
- 迁移(`_do_migration`)和崩溃恢复(`_reset_after_crash`)逻辑不动
- Model Scheduler 的加载策略不动
- External baseline 探针算法不动(当前逻辑正确,问题不在这里)
- 前端 VRAM 面板展示不动(后端记账正确后前端自然显示正确)

## 设计要点

### 新对象: `InferenceLease`

```python
# engine/vram_allocator.py 新增
class InferenceLease:
    """Per-task inference allocation holder.

    Lifecycle: acquired before GPU stage, released after all GPU-bound
    stages (gpu + export) complete. Supports OOM bump-and-retry inside
    the lease scope without leaking allocations.
    """
    _allocation: InferenceAllocation
    _allocator: "VRAMAllocator"
    _model_id: str
    _weight_mb: int

    async def bump_and_retry_once(self, new_estimate_mb: int) -> None:
        """Release current allocation and re-request with bumped estimate.
        Called by caller in OOM retry path."""
        ...

    async def __aenter__(self) -> "InferenceLease": ...
    async def __aexit__(self, ...) -> None:
        """Always releases the allocation, even on exception."""
        ...
```

### Allocator 新接口

```python
class VRAMAllocator:
    async def reserve_for_task(
        self,
        *,
        model_id: str,
        estimate_mb: int,
        weight_mb: int,
    ) -> InferenceLease:
        """Request inference allocation wrapped in a lease.
        Internally calls existing request_inference; returned lease
        owns the allocation and its lifecycle."""
```

### Pipeline 侧调用(概念示意,具体位置 Worker 决定)

```python
# 大致在 pipeline 层协调 gpu + export stage 的地方
estimate_mb = model_worker.estimate_inference_mb(sequence.options)
async with allocator.reserve_for_task(
    model_id=sequence.model,
    estimate_mb=estimate_mb,
    weight_mb=model_worker.weight_vram_mb,
) as lease:
    try:
        await gpu_stage.run(sequence)
    except OOMError:
        bump = model_worker.resolve_oom_bump_target_mb()
        await lease.bump_and_retry_once(bump)
        await gpu_stage.run(sequence)
    await export_stage.run(sequence)
# lease 自动释放 — 此时 mesh 已在 CPU,CUDA 显存真实回收
```

### ModelWorker 瘦身

```python
class ModelWorker:
    # 保留
    async def load(self) -> None: ...                    # weight 生命周期
    async def unload(self) -> None: ...
    async def run_batch(self, ...) -> list[Result]: ...  # 不再自己 request/release

    # 新增 / 暴露
    def estimate_inference_mb(self, options: dict) -> int:
        """基于当前 self.inference_vram_mb 返回估算"""

    def resolve_oom_bump_target_mb(self) -> int:
        """从私有变 public,供 lease 上层调"""

    async def apply_successful_inference_measurement(self) -> None:
        """NVML 测量后更新 EMA;pipeline 层成功后调用"""

    # 删除
    # async def run_inference(self, ...)  ← 整个方法删掉或改成纯粹的 run_batch 转发
```

### Dead code 清理

`stages/gpu/scheduler.py`:
- 删 `configure_inference_admission`
- 删 `_acquire_inference_allocation` 或把它改成纯 slot 调度(不再尝试 inference booking)
- 更新 `GPUSlotScheduler.__init__` 移除 `_inference_allocator` / `_inference_model_name` /
  `_inference_device_id` / `_estimate_inference_vram_mb` / `_inference_allocations_by_device`
  这些字段

## 文档更新(必做)

1. **`.ai/vram-management-design.md`** — 更新以下章节:
   - §1 架构总览:在"Model Worker"框内标注"不负责 inference allocation 生命周期"
   - §2 接口定义:VRAMAllocator 新增 `reserve_for_task` + `InferenceLease` 定义
   - §3(或相应职责边界章节):明确"inference allocation 生命周期 = task 生命周期,
     由 pipeline / stage 协调层拥有;ModelWorker 只提供估算 + 执行"
   - 新增一节"决策:为何搬离 ModelWorker" 带链接指向本 plan + decisions.md

2. **`.ai/decisions.md`** — 追加条目:
   ```
   ## 2026-04-18 — Inference allocation 生命周期从 ModelWorker 搬到 pipeline

   **动机**: 观测到任务 export 阶段 (~1s) inference allocation 已释放但 mesh 仍
   在 CUDA,面板 4 GB 错位显示为"外部占用"。

   **决策**: inference allocation 是 per-task 资源,生命周期覆盖 gpu + export 两个
   GPU-bound stage。由 pipeline 层通过 InferenceLease context manager 持有。
   ModelWorker 退出 allocation 管理职责。

   **替代方案**:
   - A. 把 mesh 同步 .cpu() 后再 release_inference —— 之前 c61a17a 回滚过,
     会触发 SIGBUS,否决。
   - B. 忽略面板误显示 —— 用户明确要求记账正确,否决。

   **落地**: 见 `.ai/plan/2026-04-18-inference-lease-lifecycle.md`
   ```

## Implementation Plan

### Task 1 — 新增 `InferenceLease` + `reserve_for_task`
- 在 `engine/vram_allocator.py` 定义 `InferenceLease` 类和 `reserve_for_task` 方法
- 实现 `__aenter__` / `__aexit__` / `bump_and_retry_once`
- 单元测试:正常释放、异常路径释放、bump 前后 allocation ID 变化

### Task 2 — `ModelWorker` 职责剥离
- 删除(或改写)`run_inference`,不再持有 inference allocation
- 新增 `estimate_inference_mb`、将 `_resolve_oom_bump_target_mb` 改为 public
- 把 `_apply_successful_inference_measurement` 改为 public
- `run_batch` 保留作为直接的执行入口
- 调整现有测试(test_model_worker.py)

### Task 3 — Pipeline / GPU stage 接线
- 找到协调 gpu stage + export stage 的位置(engine/pipeline.py 或类似),
  用 `async with allocator.reserve_for_task(...) as lease` 包裹这两个 stage
- OOM 重试逻辑迁移到这里
- `_apply_successful_inference_measurement` 在 lease 正常退出前触发
- 保证异常路径 lease 正确释放

### Task 4 — 清理 scheduler 死代码
- 删除 `configure_inference_admission` / `_acquire_inference_allocation` 及相关字段
- 清理 `GPUSlotScheduler.acquire` 里调用死代码的分支
- 保留 scheduler 作为纯 slot 调度器

### Task 5 — 回归与新测试
- 现有 207 tests 通过(调整签名)
- 新增集成测试:完整 task 走完 `used_inference_vram_mb > 0` 持续覆盖 gpu + export
- 新增测试:OOM 场景 lease 自愈正确
- 新增测试:异常路径 lease 正确释放

### Task 6 — 文档
- 更新 `.ai/vram-management-design.md`
- 追加 `.ai/decisions.md` 条目

### Task 7 — 生产验证
- 部署后复现原场景,确认面板在 gpu + export 全程都显示"推理 > 0, 外部 = 0"
- 此步勾选 AC 最后一条

## Notes

- **SIGBUS 约束**: 本次不涉及 mesh 同步 CPU 转换,沿用现有 `_worker_process_main`
  的 `del results + gc.collect() + empty_cache()` 模式。
- **迁移路径**: `_do_migration` 发生在 `ModelWorker.run_inference` 的 request_inference
  返回之后、_run_batch 之前。搬走后,迁移由谁触发需要 Task 3 明确 —— 如果 lease
  在 pipeline 层,迁移信号要能传到 ModelWorker 或 allocator。细节在 Task 3 设计时
  再拍(可能需要让 `request_inference` 的迁移返回值由 lease 接管并调 worker 的
  `_do_migration`)。
- **向后兼容**: 已经有 `acquire_inference`(deprecated wrapper)的客户端现在就没人调
  (`configure_inference_admission` 没被配置过),所以可以直接删除不留兼容层。
