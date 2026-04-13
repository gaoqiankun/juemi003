# VRAM allocator X3 — L1 inference estimate sanity check + L3 Trellis2 mesh CPU transfer
Date: 2026-04-13
Status: done

## Summary

闭合 Phase 1-5 review 最后两项（L1 + L3），单 commit 交付：

- **L1**：provider 返回 `<=0` 的 inference 估算现在在 runtime_loader 闭包外被 `_clamp_inference_estimate_mb` 钳到 `1` 并发 `estimate_inference_vram_mb_nonpositive` warning（含 `model` / `raw` / `batch_size` / `options` 便于 operator 定位）；三个 mock provider（trellis2 / hunyuan3d / step1x3d）同步加显式 `max(..., 1)` 表达下限意图
- **L3**：`Trellis2Provider.run_batch` 在 `_run_single` 后通过 `await asyncio.to_thread(_move_mesh_to_cpu, mesh)` 把 `vertices` / `faces` / `coords` / `attrs` + `layout` dict value 从 CUDA 搬到 CPU，消除"allocator 已释放 inference budget 但 NVML 仍占"的窗口期错位；helper defensive best-effort，缺字段 / 非 tensor / `setattr` 失败静默跳过
- L3 pre-existing 测试 `test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu[asyncio]` 从 fail 变 pass；新增 L1 参数化单元测试覆盖 `-5000 / 0 / 1 / 5000` 四档

## Key Decisions

1. **L1 走边界 + Mock 双保险**：边界层（`_clamp_inference_estimate_mb` module-level helper）单一防御点，未来新 provider 忘夹紧也会被 warning 曝光；mock 显式 `max(..., 1)` 表达"这不是巧合"——两者互补不冗余
2. **`<=0` 钳到 1 而不是 fail fast**：与 allocator 既有 `_normalize_vram_mb` 行为一致，保持容错可观测而非强硬失败，真正定位靠 log + metrics
3. **L3 helper `defensive best-effort`**：mesh 字段可能随 trellis2 pipeline 版本演化，`hasattr` / `is_cuda` 过滤 + `setattr` `try/except` 吞掉，不让 run_batch 因 mesh 变更意外挂掉
4. **L3 CPU move 放 `asyncio.to_thread`**：与 `_run_single` 一致走 worker thread，避免 `.cpu()` PCIe D2H 传输 block event loop
5. **L1 clamp 抽到 module level 而非 runtime_loader 闭包内**：保持 `runtime_loader` 复杂度 ≤10（不触发 C901 ruff），且让测试可以直接 `from gen3d.api.server import _clamp_inference_estimate_mb` 单元调用，不用重度 monkeypatch `create_app` / TestClient
6. **不对称扩展到 hunyuan3d / step1x3d real provider 的 mesh CPU 搬迁**：只有 Trellis2 有明确测试契约，延后到 X4 if needed

## Changes

- `api/server.py` (+42 / -2)：新增 module-level `_summarize_inference_options` 和 `_clamp_inference_estimate_mb`（紧邻 `_detect_device_total_vram_mb`）；`runtime_loader` 闭包内的 `estimate_inference_vram_mb` 改为委托 helper
- `model/trellis2/provider.py` (+45 / -1)：新增 module-level `_move_mesh_to_cpu(mesh)` + `_detach_cpu_tensor(value)` helper（`is_cuda` guard + `detach` + `detached.cpu` + `try/except`）；`Trellis2Provider.run_batch` 在 `_run_single` 后 `await asyncio.to_thread(_move_mesh_to_cpu, mesh)`；`MockTrellis2Provider.estimate_inference_vram_mb` 加显式 `max(..., 1)`
- `model/hunyuan3d/provider.py` (+5 / -2)：`MockHunyuan3DProvider.estimate_inference_vram_mb` 加显式 `max(..., 1)`
- `model/step1x3d/provider.py` (+5 / -2)：`MockStep1X3DProvider.estimate_inference_vram_mb` 加显式 `max(..., 1)`
- `tests/test_vram_inference_estimate_clamp.py`（新，62 行）：纯单元测试直接 import `_clamp_inference_estimate_mb`，4 档参数化 `-5000 / 0 / 1 / 5000`，`monkeypatch.setattr(server_module, "_logger", FakeLogger())` 捕获 warning 字段断言

## Notes

- Pytest: `216 passed / 0 failed`（baseline X2 = 211 passed / 1 failed → 216 / 0；L3 pre-existing failure 已修，+4 个 L1 新参数化测试）
- Ruff:
  - `api/server.py` 从 6 errors → **5 errors**（`runtime_loader` C901 消失，`create_app` 复杂度 213 → 209 回到 X2 baseline —— helper 抽出让 `create_app` 也顺手瘦了一点；剩余 5 条 `create_app` / `create_model` / `update_settings` C901 + 两条 F841 均为 pre-existing 仓库债）
  - 其他 7 个改动 / 新增文件 focused ruff check `All checks passed!`
- 一次 Revision：first-pass Worker 产物功能 AC 全 PASS，但把 `runtime_loader` 推到 C901(12>10) + 测试用 6 处 monkeypatch 触达闭包 + `_detach_cpu_tensor` 有冗余 cpu getattr。Revision 1 用 `.ai/tmp/context-vram-allocator-x3-rev1.md` 下发三项 targeted fix，一次性解决
- Friction（供 `.ai/friction-log.md`）：first-pass 把 clamp 逻辑塞在闭包里是本能反应但会把复杂度推过阈值 + 让测试难写 —— 下次写类似 instrumentation 应该先想"能不能放 module level"

闭合 Phase 1-5 review 遗留的最后两项：

- **L1 — `estimate_inference_vram_mb` 下限 sanity check**：provider 返回 `<=0` 会被 `_normalize_vram_mb` 静默钳到 1，让 allocator 误认为推理只需 1 MB，产生调度错位但无法感知。边界 + mock 双保险兜底。
- **L3 — `test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu[asyncio]` pre-existing 失败项**：`Trellis2Provider.run_batch` 未把 mesh tensors 从 GPU 搬到 CPU，推理完成后 allocator 释放 inference budget 时 GPU VRAM 尚未真正回收，造成"显存账本已释放但 NVML 仍占"的窗口期错位。

## 背景与现状

### L1 — provider estimate 现状

| Provider | 位置 | `estimate_inference_vram_mb` 实现 | 下限钳紧 |
|---|---|---|---|
| BaseModelProvider (默认) | `model/base.py:57-59` | `max(total - weight, 1)` | ✅ |
| Trellis2 real | `model/trellis2/provider.py:186-194` | `max(total - weight, 1)` | ✅ |
| Hunyuan3D real | `model/hunyuan3d/provider.py:184-187` | `max(total - weight, 1)` | ✅ |
| Step1X3D real | `model/step1x3d/provider.py:220-223` | `max(total - weight, 1)` | ✅ |
| Trellis2 mock | `model/trellis2/provider.py:41-43` | `max(batch_size, 1) * 20_000 - weight` | ❌ |
| Hunyuan3D mock | `model/hunyuan3d/provider.py:50-52` | `max(batch_size, 1) * 24_000 - weight` | ❌ |
| Step1X3D mock | `model/step1x3d/provider.py:51-53` | `max(batch_size, 1) * 27_000 - weight` | ❌ |

边界层（`api/server.py:1340-1346`）当前直接 `return runtime.provider.estimate_inference_vram_mb(...)`，无钳紧也无 warning。allocator `_normalize_vram_mb`（`engine/vram_allocator.py:18-23`）把结果最低钳到 1，但这是最后防线，此时已静默。

### L3 — Trellis2 run_batch 未 CPU 移位

`model/trellis2/provider.py:210-251`：
```python
async def run_batch(...):
    for prepared_input in images:
        mesh = await asyncio.to_thread(self._run_single, image, options, emit_stage)
        results.append(GenerationResult(mesh=mesh, ...))
    return results
```

`_run_single` 返回的 mesh 直接包进 `GenerationResult` 返回，未搬迁到 CPU。测试（`tests/test_api.py:4447-4490`）用 FakeMesh + FakeTensor 明确编码契约：

- 字段：`vertices`, `faces`, `coords`, `attrs`, `layout`（dict，value 是张量）
- 张量接口：`.is_cuda`（判断 cuda）、`.detach()`、`.cpu()`（返回新 CPU 张量，不 mutate）

修复契约：`run_batch` 返回前，对 mesh 的已知字段 + `layout` dict value 做 "若 `is_cuda` 则 reassign 为 `.detach().cpu()` 结果"。CPU move 放进 `asyncio.to_thread` 执行以免 block event loop。

## Acceptance Criteria

### L1 — 边界 + Mock 双保险

- **AC1** — `api/server.py:1340-1346` 的 `estimate_inference_vram_mb` 闭包包装层加夹紧逻辑：provider 返回值 `<=0` 时钳到 `1` 并 `_logger.warning("estimate_inference_vram_mb_nonpositive", model=..., raw=raw_value, clamped=1)`；`>=1` 时直传（不打 log）
- **AC2** — warning 必须包含以下字段，便于 operator 定位：`model`（模型名）、`raw`（provider 原始返回）、`batch_size`、`options`（截断版或关键 key）
- **AC3** — `model/trellis2/provider.py:41-43` `MockTrellis2Provider.estimate_inference_vram_mb` 包一层 `max(..., 1)`
- **AC4** — `model/hunyuan3d/provider.py:50-52` `MockHunyuan3DProvider.estimate_inference_vram_mb` 包一层 `max(..., 1)`
- **AC5** — `model/step1x3d/provider.py:51-53` `MockStep1X3DProvider.estimate_inference_vram_mb` 包一层 `max(..., 1)`
- **AC6** — mock 三家修复后运行时数值保持不变（当前所有 mock 配置下 `batch*N - weight` 都 > 0，`max(..., 1)` 只是显式表达意图），不触发已有测试的 assertion

### L3 — Trellis2 mesh CPU 搬迁

- **AC7** — `model/trellis2/provider.py` 新增 module-level 或类内 helper `_move_mesh_to_cpu(mesh)`，遍历字段 `vertices` / `faces` / `coords` / `attrs` + `layout` dict value；字段存在且张量 `.is_cuda` 为真时，`setattr(mesh, field, tensor.detach().cpu())` / `layout[key] = tensor.detach().cpu()`
- **AC8** — helper 对缺失字段（`hasattr` 为 False）静默跳过；对非 tensor 值（无 `.is_cuda` 属性或非可调用 `.cpu`）静默跳过；layout 非 dict 时静默跳过 —— 不 crash，实现"defensive best-effort"
- **AC9** — `Trellis2Provider.run_batch` 在 `mesh = await asyncio.to_thread(self._run_single, ...)` 后、`results.append(...)` 前调用 `await asyncio.to_thread(_move_mesh_to_cpu, mesh)`（避免 block event loop；move helper 本身是纯 CPU/PCIe 操作）
- **AC10** — `MockTrellis2Provider.run_batch` **不** 调用 helper（mock mesh 是 dict，没有张量属性），保持既有行为

### 测试与质量

- **AC11** — `tests/test_api.py::test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu[asyncio]` **通过**（即本 plan 闭合 L3 的唯一直接验证）
- **AC12** — 新增 `tests/test_vram_inference_estimate_clamp.py`（或合入 `tests/test_api.py`）覆盖 L1 行为：
  - fake provider 返回 `-5_000` → 闭包钳到 `1` + 产生 warning 记录
  - fake provider 返回 `0` → 闭包钳到 `1` + warning
  - fake provider 返回 `1` → 原样直传 + 无 warning
  - fake provider 返回 `5_000` → 原样直传 + 无 warning
  - 使用 `caplog` 或注入 logger 记录 warning 行为（与现有 structlog 模式一致）
- **AC13** — `uv run python -m pytest tests -q` baseline **≥ 212 passed / 0 failed**（X2 收尾 211 passed / 1 L3 failed，X3 修 L3 → 212 passed；+ L1 新测试进一步增加 passed 数）
- **AC14** — `uv run ruff check engine/vram_allocator.py observability/metrics.py storage/settings_store.py model/trellis2/provider.py model/hunyuan3d/provider.py model/step1x3d/provider.py` focused check 通过
- **AC15** — 跨模块行为变更 + friction 通过 `.ai/tmp/report-vram-allocator-x3.md` surface 给 Orchestrator

## 关键设计决策

1. **L1 走边界 + Mock 双保险**：边界层（closure）提供单一防御点，未来新 provider 忘记夹紧也会被 warning 曝光；mock 同步修复是表达"这是预期行为，不是巧合"的形式——两者互补，不冗余。
2. **边界层 `<=0` 钳到 1 而不是抛异常**：历史上 allocator `_normalize_vram_mb` 已经这么做，X3 只是在更上层提前钳 + log，保持"容错 + 可观测"而非"fail fast"。真正的错误定位交给 log + metrics。
3. **L3 helper 走 "defensive best-effort"**：mesh 字段可能随 trellis2 pipeline 版本演化，hard-coded 字段列表是现实权衡；非期望字段（如 `voxel_size`、`float`）被 `hasattr` + `is_cuda` 过滤，不 crash。
4. **L3 CPU move 放在 `asyncio.to_thread`**：与 `_run_single` 一致走 worker thread，避免 `.cpu()` PCIe D2H 传输 block event loop；worker 进程内串行，没有并发安全问题。
5. **不动 hunyuan3d / step1x3d real provider 的 run_batch**：只有 Trellis2 有明确测试 + mesh 对象结构契约，对称扩展延后到 X4（若真有同类问题报告）。

## 影响模块（Impact Map）

- `api/server.py`：`estimate_inference_vram_mb` 闭包（:1340-1346）加钳紧 + warning
- `model/trellis2/provider.py`：新增 `_move_mesh_to_cpu` helper；`Trellis2Provider.run_batch` 调用 helper；`MockTrellis2Provider.estimate_inference_vram_mb` 加 `max(..., 1)`
- `model/hunyuan3d/provider.py`：`MockHunyuan3DProvider.estimate_inference_vram_mb` 加 `max(..., 1)`
- `model/step1x3d/provider.py`：`MockStep1X3DProvider.estimate_inference_vram_mb` 加 `max(..., 1)`
- `tests/test_api.py` 或新文件 `tests/test_vram_inference_estimate_clamp.py`：L1 四档数值测试
- （L3 测试已存在于 `tests/test_api.py:4447-4490`，本 plan 目标是让它从 fail 变 pass，不新增）

## 工作量划分（单 Worker 一次交付）

Worker 一次完成 AC1-AC14。理由：
- L1 和 L3 零耦合但规模都很小（L1 ~15 行生产代码 + 4 档测试；L3 ~20 行生产代码 + 复用已有测试）
- 合并提交更能准确表达"X3 = Phase 1-5 review 最后两项收尾"的语义

## 风险与回滚

- **风险 1**：L3 helper 对真实 `o_voxel` mesh 的某些字段无法 `setattr`（若是 frozen dataclass / slots / 只读 property）→ 退路：helper 在 `setattr` 外 `try/except (AttributeError, TypeError)`,吞掉并 `_logger.warning("mesh_field_not_assignable", field=...)`,不让整个 run_batch 挂
- **风险 2**：L3 CPU move 对超大 mesh 有可感知延迟（几百 MB 级别）→ 这正是要做的,搬到 CPU 是显存账本 vs NVML 一致性的必需。若真成为瓶颈可在后续 plan 加 pinned memory / async copy 优化
- **风险 3**：L1 warning 在高频 path 上产生日志噪声 → 正常情况下不会触发（provider 都 >=1）,只在有 bug 的场景出现,频率受限
- **回滚方案**：单 commit,`git revert` 即可回到 e9febb0 (X2) baseline

## Out of Scope

- Hunyuan3D / Step1X3D real provider 的 mesh CPU 搬迁对称扩展 → X4（需先有实际测试/bug 报告）
- `estimate_weight_vram_mb` / `estimate_vram_mb` 的类似 sanity check → X4（Phase 1-5 review 未标为 HIGH/MEDIUM 优先级）
- Phase 6 Admin UI 显存明细展示 → 独立前端 plan
- README 中英双语 + 重构 → 独立 plan
- provider interface 重构为 `@final` 壳 + `_compute_inference_vram_mb` 抽象方法 → 过度工程,保持现状

## Report

Worker 在 `.ai/tmp/report-vram-allocator-x3.md` 汇报：
- 实际 diff 概要（文件 + 行数）
- pytest 结果（L3 测试是否从 fail 变 pass、新增 L1 测试的 passed 数）
- ruff focused check 结果
- 是否遇到 o_voxel mesh 真实结构的 setattr 风险 (AC8 `try/except` 是否真正被触发)
- 跨模块行为变更（供 `.ai/decisions.md`）
- 遇到的 friction（供 `.ai/friction-log.md`）
- 任何偏离本 plan 的决策及理由
