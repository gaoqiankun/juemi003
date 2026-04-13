# VRAM allocator X2 — 内部争抢超时 + Prometheus 指标
Date: 2026-04-13
Status: done

## Summary

闭合 Phase 1-5 review 遗留的 M4（内部争抢超时）+ L2（Prometheus 指标）两项缺陷，单 commit 一次交付：

- `VRAMAllocator.acquire_inference` 新增 **独立的内部争抢计时器**，默认 60s，超时抛 `InternalVRAMContentionTimeoutError`；与外部占用计时器完全解耦，evict 成功后两个计时器同步进入新 round。
- `GPUStage.run` retry 路径显式排除内部争抢超时（不走 reload 迁移），外部超时 + scheduler shutdown 的 single-shot retry 语义保持不变。
- allocator 新增 `VRAMMetricsHook` dataclass + `set_metrics_hook` 注入点，新增三个 Prometheus 指标（`vram_acquire_inference_total` counter、`vram_acquire_inference_wait_seconds` histogram、`vram_evict_total` counter），engine 模块保持零 observability import。
- `api/server.py` startup 注入具体 hook、预热 device label、persist/live-apply `internalVramWaitTimeoutSeconds` 动态配置。
- 测试覆盖 5 种 outcome（immediate / after_wait / after_evict / timeout_internal / timeout_external）+ 内外计时器独立 + evict reset 重置 + AC7 retry 路径隔离 + admin settings GET/PATCH + `/metrics` smoke。

## Key Decisions

1. **内部超时默认 60s**（>外部 30s）：内部争抢更可能自然恢复，留宽容度；仍比 task 级 timeout 短，能快速暴露故障
2. **内部超时不走 reload 迁移**：内部争抢说明本卡显存确实不够或同卡模型未正常释放，迁移其他卡无法修复根因；保持 5xx 快速失败由 metrics/log 暴露真因
3. **Metrics hook 走 callback 注入**：与 `set_evict_callback` / `set_vram_probe` / `set_external_vram_wait_timeout_seconds` pattern 一致，allocator 零 observability 依赖，mock 自然隔离
4. **Hook 异常吞掉**：observability 不影响主流程，三个 emit 点对每个 callback 独立 `try/except Exception: _logger.warning(...)`
5. **immediate outcome 也 emit histogram wait=0.0**：outcome label 切片即可区分 P50/P99 来源，不丢失 instrumentation 一致性
6. **M4/L2 合并单 commit**：两者都在同一个 wait loop 做 instrumentation，拆分只会制造 merge conflict
7. **`stages/gpu/stage.py` 显式 `except InternalVRAMContentionTimeoutError: raise`**：即使与 External 是姐妹类不会被误杀，显式 catch 防未来重构 accidentally 合并

## Changes

- `engine/vram_allocator.py` (+245 / -25)：`InternalVRAMContentionTimeoutError`、`VRAMMetricsHook` dataclass + 3 Protocol callbacks、`set_metrics_hook` / `set_internal_vram_wait_timeout_seconds` / `internal_vram_wait_timeout_seconds` getter、`_touch_internal_wait_or_raise` / `_raise_internal_contention_timeout` / `_emit_acquire_result` / `_emit_evict_result` / `_wait_seconds` / `_resolve_success_outcome` helpers、`acquire_inference` 集成独立计时器 + hook emit 点
- `stages/gpu/stage.py` (+6 / -1)：retry 循环显式排除 `InternalVRAMContentionTimeoutError`
- `observability/metrics.py` (+63 / -0)：`_VRAM_ACQUIRE_INFERENCE_TOTAL` / `_VRAM_ACQUIRE_INFERENCE_WAIT` / `_VRAM_EVICT_TOTAL` 三个指标、3 个 helper、`initialize_vram_metrics(device_ids)` 预热
- `storage/settings_store.py` (+1)：`INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY = "internal_vram_wait_timeout_seconds"`
- `api/server.py` (+73 / -2)：startup 注入 `VRAMMetricsHook` 委托 observability helper、lifespan 预热 VRAM metrics label、load persisted `internalVramWaitTimeoutSeconds`、GET settings 暴露字段、PATCH 校验 `>0` + live apply
- `tests/test_vram_allocator.py` (+241)：`test_internal_timeout_error_is_allocator_error_subclass`、`test_internal_contention_timeout_raises_when_evict_is_disabled`、`test_internal_and_external_wait_timers_are_independent`、`test_evict_success_resets_internal_wait_round`、`test_metrics_hook_records_all_acquire_outcomes`（五种 outcome 全覆盖）
- `tests/test_gpu_stage_migration.py` (+29)：`test_acquire_does_not_retry_on_internal_contention_timeout`
- `tests/test_api.py` (+53)：admin settings GET 暴露字段断言、PATCH 合法值 live apply、PATCH `0` 返回 422、`/metrics` smoke 断言新 VRAM series

## Notes

- Pytest: `1 failed, 211 passed`（baseline 203→211 是因为 AC14/AC15 新增测试）；唯一 failure 是 `test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu[asyncio]`，属 L3 pre-existing，已在本 plan Out of Scope 标明，留待 X3
- Ruff: 全仓 `ruff check .` 仍红（pre-existing lint debt），但新增 / 改动的核心文件 `engine/vram_allocator.py` / `observability/metrics.py` / `storage/settings_store.py` / `tests/test_gpu_stage_migration.py` 的 focused ruff check 全 pass
- Code-review 脚本对 allocator 的 size/function-size 提示是 M4+L2 instrumentation 内联的必然结果，Worker 已通过抽出 4 个 helper 控制主循环可读性，可接受
- Friction（供 `.ai/friction-log.md`）：Worker 执行时遇到 sandbox `bwrap: loopback: Failed RTM_NEWADDR` 报错，escalated command execution 后恢复；仓库 `ruff check .` 历史债依旧会让 focused 模式成为 validate 阶段的现实选择

## Goal

闭合 Phase 1-5 review 遗留的两项可观测性与健壮性缺陷：

- **M4 — 内部争抢超时**：`VRAMAllocator.acquire_inference` 的 wait loop 当前只对"外部占用"计时（`_track_external_occupation_wait`），`evict` 不可用或失败后会进入无上限 `asyncio.sleep` loop。必须加**独立的内部争抢计时上限**，超时抛 `InternalVRAMContentionTimeoutError`，冒泡到 API 5xx（不走 Phase 5 reload 迁移 retry，语义与外部占用区分）。
- **L2 — Prometheus 指标**：VRAM allocator 关键事件目前零可观测性，Phase 1-5 期间的挂死/超时靠日志 + 复盘定位。新增 `observability/metrics.py` 三个指标并通过 callback hook 注入到 allocator，保持 engine 模块零依赖。

## 背景与现状

### M4 — 当前 wait loop 行为（`engine/vram_allocator.py:205-256`）

```
acquire_inference():
    while True:
        _try_acquire_inference() → 成功返回
        _track_external_occupation_wait()  # 只计外部占用
        if evict 可用 and 超过 _EVICT_WAIT_WINDOW_SECONDS(2s):
            await evict_callback()
            evicted=True → 重试
            evicted=False → evict_allowed=False（之后永远不再 evict）
        asyncio.sleep(_INFERENCE_WAIT_SECONDS)
```

**失效场景**：同卡两个模型 A/B 都在推理，A 的 `inference_allocations` 未释放；C 请求 acquire_inference 到达 → `_try_acquire_inference` 失败 → effective_free >= booked_free（无外部占用，`_track_external_occupation_wait` 永远返回 None）→ evict 过滤后找不到 idle victim（A/B 都是 active）→ `evict_allowed=False` → 进入无限 sleep loop。

### L2 — 现有 metrics 基础设施（`observability/metrics.py`）

- 共享 `CollectorRegistry`
- helper：`initialize_gpu_slots / set_queue_depth / set_gpu_slot_active / observe_task_duration / observe_stage_duration / increment_task_total / increment_webhook_total / render_metrics`
- engine 模块**零 import observability**（跨层解耦原则），allocator 现有 `set_evict_callback / set_vram_probe / set_external_vram_wait_timeout_seconds` 全走 runtime setter pattern

## Acceptance Criteria

### M4 — 内部争抢超时

- **AC1** — allocator 新增 `_DEFAULT_INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS = 60.0`、`set_internal_vram_wait_timeout_seconds(seconds)` / `internal_vram_wait_timeout_seconds` getter，与外部超时 setter 对称；`None` / `<=0` 回退默认值
- **AC2** — `acquire_inference` wait loop **独立计时**内部争抢时长（从首次 `_try_acquire_inference` 失败起算），总等待超过上限抛新异常 `InternalVRAMContentionTimeoutError(VRAMAllocatorError)`；不复用外部占用计时器
- **AC3** — 内部计时与外部计时**互相独立**：外部占用出现不重置内部计时，内部超时时不看外部占用状态；两种超时抛不同异常子类
- **AC4** — `evict_callback` 成功 evict 并成功 `_try_acquire_inference` 后，**内部计时器重置**（和外部计时器语义一致，代表"进入新一轮 wait"）
- **AC5** — 新增持久化动态配置 key `INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY = "internal_vram_wait_timeout_seconds"` 于 `storage/settings_store.py`
- **AC6** — `api/server.py` startup 时从 `SettingsStore` 读取并注入 allocator；GET `/api/admin/settings` 暴露 `internalVramWaitTimeoutSeconds` 字段；PATCH `/api/admin/settings` 校验 `> 0` 并 live apply（与 `externalVramWaitTimeoutSeconds` 同一个 endpoint 的同级字段）
- **AC7** — `GPUStage.run` retry 循环：`InternalVRAMContentionTimeoutError` 不进入 reload 迁移路径（不合并到 `ExternalVRAMOccupationTimeoutError` 的 migration_attempted 守卫），直接冒泡到 async_engine → 任务失败 5xx；`ExternalVRAMOccupationTimeoutError` 和 `SchedulerShutdownError` 的 single-shot retry 行为**不变**

### L2 — Prometheus 指标

- **AC8** — `observability/metrics.py` 新增三个指标（共享 `REGISTRY`）：
  - `Counter` `vram_acquire_inference_total{device, outcome}`，outcome ∈ `{"immediate", "after_wait", "after_evict", "timeout_internal", "timeout_external"}`
  - `Histogram` `vram_acquire_inference_wait_seconds{device}`，buckets `(0.001, 0.01, 0.05, 0.25, 1, 5, 15, 30, 60, 120)`
  - `Counter` `vram_evict_total{device, result}`，result ∈ `{"success", "noop", "failure"}`
- **AC9** — helper 函数：
  - `increment_vram_acquire_inference(*, device: str, outcome: str) -> None`
  - `observe_vram_acquire_inference_wait(*, device: str, wait_seconds: float) -> None`
  - `increment_vram_evict(*, device: str, result: str) -> None`
- **AC10** — allocator 新增 `set_metrics_hook(hook: VRAMMetricsHook | None)` runtime setter，`VRAMMetricsHook` 是一个 Protocol / TypedDict / 简单 dataclass，包含三个可选回调字段（`on_acquire_outcome`、`on_acquire_wait`、`on_evict`），与 probe/evict 既有注入 pattern 对称
- **AC11** — allocator 在以下事件点调用 hook（hook 为 None 时完全 no-op）：
  - `acquire_inference` 返回成功（含 `immediate` / `after_wait` / `after_evict` 三种分支）→ `on_acquire_outcome` + `on_acquire_wait`
  - `acquire_inference` 抛 `InternalVRAMContentionTimeoutError` / `ExternalVRAMOccupationTimeoutError` 前 → `on_acquire_outcome(outcome=timeout_*)` + `on_acquire_wait`
  - evict_callback 返回后 → `on_evict(device, result)`（hook 调用异常不影响主流程，统一 `try/except` 吞掉）
- **AC12** — `api/server.py` startup 注入具体实现：hook 内部委托到 `observability.metrics` 对应 helper；allocator 和 engine 模块保持**零 import observability**
- **AC13** — 指标在 startup 时为已知 device 预热 label（避免首次 scrape 缺 series）：`initialize_gpu_slots` 扩展或新增 `initialize_vram_metrics(device_ids)`

### 测试与质量

- **AC14** — `tests/test_vram_allocator.py` 新增：
  - 内部争抢超时：evict 不可用（`set_evict_callback(None)`）且同卡无空闲预算，acquire_inference 在 `set_internal_vram_wait_timeout_seconds(0.05)` 后抛 `InternalVRAMContentionTimeoutError`
  - 内部/外部计时独立：构造外部占用 + 内部争抢同时存在，验证两个计时器互不重置
  - evict 成功后内部计时重置：evict_callback 首轮返回 False、第二轮返回 True → acquire 成功，不因累计时间超限而抛错
  - metrics hook 调用：fake hook 记录调用，验证 `immediate` / `after_wait` / `after_evict` / `timeout_internal` / `timeout_external` 五种 outcome 都被正确触发
- **AC15** — `tests/test_api.py` 或新增 `tests/test_admin_settings.py`（沿用 Phase 4c 的既有测试）：
  - GET `/api/admin/settings` 返回 `internalVramWaitTimeoutSeconds`
  - PATCH 合法值 live apply
  - PATCH `<= 0` 返回 422
- **AC16** — 可选：metrics endpoint smoke test（GET `/metrics` 含新 series 名），如已有 metrics 测试就扩展，没有就跳过
- **AC17** — `uv run python -m pytest tests -q` baseline ≥ **203 passed / 1 failed**（1 failed = L3 pre-existing，X2 不动）
- **AC18** — `uv run ruff check .` 不引入新 issue
- **AC19** — 跨模块行为变更 + friction 通过 `.ai/tmp/report-vram-allocator-x2.md` surface 给 Orchestrator，Orchestrator validate 阶段写入 `.ai/decisions.md` / `.ai/friction-log.md`

## 关键设计决策

1. **内部超时默认 60s**：比外部 30s 更宽容（内部争抢更可能自然恢复），仍比任务级 task timeout 短，能在故障时快速暴露而不影响正常 batch 排队。
2. **内部超时不走 reload 迁移 retry**：内部争抢说明本卡显存确实不够（或同卡模型未正常释放），迁移到其他卡并不能修复这个根因；保持 5xx 快速失败，让 operator 从 metrics / log 看到真因。
3. **Metrics hook 走 callback 注入**：与 `set_evict_callback` / `set_vram_probe` / `set_external_vram_wait_timeout_seconds` pattern 一致，allocator 保持零 observability 依赖，mock 测试自然隔离。
4. **Hook 异常吞掉**：观测性 hook 不应影响主流程，hook 内部任何异常（Prometheus 注册冲突、label 参数错误等）用 `try/except Exception: logger.warning(...)` 吞掉。
5. **Histogram buckets 覆盖 0.001s ~ 120s**：immediate path 要能体现毫秒级，timeout path 要覆盖到 60s 内部/30s 外部上限，留余量到 120s。

## 影响模块（Impact Map）

- `engine/vram_allocator.py`：新增 `InternalVRAMContentionTimeoutError`、内部计时字段、`set_internal_vram_wait_timeout_seconds` setter、`VRAMMetricsHook` Protocol、`set_metrics_hook` setter、`acquire_inference` wait loop 集成两个计时器 + hook emit 点
- `storage/settings_store.py`：新增 `INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY`
- `api/server.py`：startup 读取 + 注入 allocator、GET/PATCH `/api/admin/settings` 暴露 `internalVramWaitTimeoutSeconds`、startup 构造 metrics hook 并 `set_metrics_hook` 到 allocator、`initialize_vram_metrics(device_ids)` 预热
- `stages/gpu/stage.py`：`GPUStage.run` retry 循环区分 `InternalVRAMContentionTimeoutError`（不 retry）与 `ExternalVRAMOccupationTimeoutError`（保留 single-shot reload retry）
- `observability/metrics.py`:新增 3 个指标 + 3 个 helper + `initialize_vram_metrics`
- `tests/test_vram_allocator.py`:内部超时 + 独立计时 + hook 测试
- `tests/test_api.py` 或新文件:admin settings PATCH/GET 覆盖

## 工作量划分（单 Worker 一次交付）

Worker 一次完成 AC1-AC18，不拆分阶段。理由：
- M4 和 L2 在同一个 `acquire_inference` wait loop 里 instrumentation，拆分反而制造 merge conflict
- 每项改动独立可测，单 commit 提交清晰

## 风险与回滚

- **风险 1**：hook 注入异常破坏 allocator 主路径 → mitigated by AC11 的 try/except 吞掉
- **风险 2**：内部超时误杀正常 batch 排队 → 默认 60s + 可动态调，运维可根据实际负载调整；发现问题可立刻 PATCH 上调
- **回滚方案**：单 commit，`git revert` 即可回到 3dfbeca baseline

## Out of Scope

- L1 `estimate_inference_vram_mb` 下限 sanity check → 下一个 plan (X3)
- L3 `test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu[asyncio]` pre-existing 失败项 → 下一个 plan (X3)
- Phase 6 Admin UI 显存明细展示 → 独立前端 plan
- README 中英双语 + 重构 → 独立 plan

## Report

Worker 在 `.ai/tmp/report-vram-allocator-x2.md` 汇报：
- 实际 diff 概要（文件 + 行数）
- pytest 结果（passed / failed 数量，L3 pre-existing 失败项需在 report 明确）
- ruff 结果
- 跨模块行为变更（供 `.ai/decisions.md`）
- 遇到的 friction（供 `.ai/friction-log.md`）
- 任何偏离本 plan 的决策及理由
