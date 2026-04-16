# VRAM Display Bug Fixes
Date: 2026-04-16
Status: done

## Goal

修复 4 个相互关联的 VRAM 显示/accounting bug，使 allocator 对 `low_vram=True` 模型（Trellis2）的显存占用有正确认知。

## Background

Trellis2 使用 `low_vram=True`：权重在 CPU，推理时才搬到 GPU，推理结束搬回。因此其 `weight_vram_mb` 理论值为 0。但当前有 4 个 bug 共同导致 allocator 错误地以为 Trellis2 常驻占用 ~17.6G 显存。

## Bugs

### Bug 1 — `_normalize_vram_mb(0)` 返回 None
- 文件：`api/helpers/vram.py:21`
- 现状：`if normalized <= 0: return None`，把 0 当"未知"处理
- 修复：改为 `if normalized < 0: return None`，接受 0 为有效值

### Bug 2 — `_SEED_MODELS` Trellis2 seed 值错误
- 文件：`storage/model_store.py`（`_SEED_MODELS` 两个 trellis2 entry）
- 现状：`weight_vram_mb: 16000`
- 修复：改为 `weight_vram_mb: 0`（low_vram=True，权重不占 GPU）
- 注意：HunyuanY3D（16000）和 Step1X3D（18000）不变，它们无 offloading

### Bug 3 — weight 测量后未同步更新 allocator
- 文件：`api/server.py`，`_on_weight_measured` 函数
- 现状：`_apply_vram_estimate_update` 更新了 DB，但 allocator 的 `budget.allocations[model]` 仍持有旧值
- 修复：DB 更新后调用 `vram_allocator.reserve(model_name, weight_vram_mb=new_mb, allowed_device_ids=all_device_ids)`
  — `reserve()` 已有"model 已在某 device 时直接更新 allocation"的逻辑，可直接复用

### Bug 4 — weight VRAM 错误使用 EMA 平滑
- 文件：`api/server.py`，`_update_vram_estimate` 函数
- 现状：weight 和 inference 都走同一套 EMA（0.7 old + 0.3 new）
- 问题：weight VRAM 是确定性值（不随 batch/options 变化），EMA 会把 0 平滑成非零
- 修复：`field_name == "weight_vram_mb"` 时直接用测量值（`new_mb = normalized_measured_mb`），跳过 EMA

## Acceptance Criteria

- [ ] `_normalize_vram_mb(0)` 返回 0，不返回 None
- [ ] `_SEED_MODELS` 中两个 trellis2 entry 的 `weight_vram_mb` 为 0
- [ ] `_on_weight_measured` 触发后，allocator 的 `budget.allocations["trellis2"]` 同步更新
- [ ] weight VRAM 测量值直接写入，不经过 EMA
- [ ] 现有测试全部通过（pytest）

## Files

- `api/helpers/vram.py` — Bug 1
- `storage/model_store.py` — Bug 2
- `api/server.py` — Bug 3 + Bug 4

## Summary

修复 4 个 VRAM accounting bug，Trellis2（low_vram=True）不再被 allocator 误以为常驻占用 ~17.6G 显存。`_normalize_vram_mb` 和 `_normalize_optional_vram_mb` 均接受 0 为有效值；Trellis2 seed 改为 0；weight 测量后实时同步 allocator；weight VRAM 不再走 EMA。226 passed。

## Key Decisions

- weight VRAM 跳过 EMA：确定性值，不应平滑；inference VRAM 保留 EMA（随 batch/options 浮动）
- allocator 同步复用 `reserve()`：已有"model 已在 device 时原地更新"逻辑，无需新增方法
