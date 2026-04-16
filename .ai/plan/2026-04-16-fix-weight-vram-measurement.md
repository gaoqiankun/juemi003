# Fix weight VRAM measurement: memory_reserved vs memory_allocated
Date: 2026-04-16
Status: done

## Goal

Fix CUDA OOM in step1x3d inference caused by inaccurate weight VRAM measurement.

**Root cause:** `_capture_cuda_baseline_mb()` in `stages/gpu/worker.py` uses
`torch.cuda.memory_allocated()` to measure the model weight footprint. This only
counts PyTorch tensor allocations (~18 GB for step1x3d), NOT the PyTorch caching
allocator's reserved blocks. The actual GPU footprint is ~28 GB (NVML-reported),
because PyTorch's caching allocator holds large memory blocks to avoid re-allocation.

**Consequence:** VRAMAllocator books step1x3d at ~18 GB instead of ~28 GB, leaving
a virtual booked_free of ~14.5 GB. If the NVML probe returns None, inference
admission sees 14.5 GB > 9 GB (estimate) → approved → OOM at inference time.

**Fix:** Use `torch.cuda.memory_reserved()` for weight reporting. This includes
caching-allocator-held blocks, closely matching actual NVML-reported usage.
Inference peak measurement must remain on `memory_allocated()` (since
`max_memory_allocated()` tracks allocations, not reservations).

## Changes

### `stages/gpu/worker.py`

**`_capture_cuda_baseline_mb()`** — extend return tuple from 3 → 4:
```
before: (torch_module, device, baseline_mb)
after:  (torch_module, device, weight_reserved_mb, inference_baseline_allocated_mb)
```
- `weight_reserved_mb = torch.cuda.memory_reserved(device)`  ← NEW
- `inference_baseline_allocated_mb = torch.cuda.memory_allocated(device)`  ← was baseline_mb

**`_worker_process_main()`** — update callers:
1. Unpack 4-tuple: `torch_module, torch_device, weight_mb, inference_baseline_mb = _capture_cuda_baseline_mb()`
2. "ready" message: `"weight_allocated_mb": weight_mb`  (was `baseline_mb`, now `memory_reserved()`)
3. `reset_peak_memory_stats` guard: `if ... and inference_baseline_mb is not None`
4. Inference peak calc: `peak_mb - inference_baseline_mb`  (was `baseline_mb`)
5. Inference peak guard: `if ... and inference_baseline_mb is not None`

## Acceptance Criteria

- [ ] `_capture_cuda_baseline_mb()` returns 4-tuple with `memory_reserved()` as first measurement value
- [ ] "ready" message `weight_allocated_mb` uses `memory_reserved()`
- [ ] Inference peak delta still computed as `max_memory_allocated() - memory_allocated_baseline`
- [ ] All guard conditions (`is not None`) reference `inference_baseline_mb` (not `weight_mb`)
- [ ] All existing tests pass
- [ ] No logic change other than the measurement switch

## Summary

`_capture_cuda_baseline_mb()` now returns both `memory_reserved()` (for weight
reporting to VRAMAllocator) and `memory_allocated()` (for inference peak delta).
Previously both used `memory_allocated()`, causing step1x3d weight to be booked
at ~18 GB instead of ~28 GB — making virtual booked_free look like 14.5 GB free
when only 2.5 GB was actually free, allowing inference to proceed → CUDA OOM.

## Key Decisions

- Use `memory_reserved()` for weight: includes PyTorch caching allocator's held
  blocks, closely matching NVML-reported usage without requiring pynvml.
- Keep `memory_allocated()` for inference peak: `max_memory_allocated()` API
  tracks allocations, not reservations; mixing them would give wrong peak delta.

## Notes

226 tests pass. Test `test_process_gpu_worker_measurement.py` updated to assert
the semantic split (reserved → weight, allocated → inference baseline).

## Expected result

With step1x3d `memory_reserved()` ≈ 28 GB (vs previous 18 GB):
- VRAMAllocator books: trellis2(16 GB) + step1x3d(28 GB) = 44 GB
- booked_free = 48537 - 44000 ≈ 4537 MB < 9000 MB (inference estimate)
- → inference BLOCKED even if NVML probe fails
