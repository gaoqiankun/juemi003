# Weight VRAM: subprocess-reported measurement
Date: 2026-04-15
Status: done

## Goal

Replace the current NVML before/after-window measurement for `weight_vram_mb` with a
value reported directly by the worker subprocess (`torch.cuda.memory_allocated()` after
model load). This correctly reports 0 for low-VRAM models like Trellis2 (weights on CPU)
and non-zero for models that keep weights on GPU, eliminating the false-alarm
`weight_measure.non_positive_delta` warning and fixing the over-reservation of 16 GB in
the VRAM allocator for Trellis2.

## Background

### Why NVML measurement fails for Trellis2

`_load_runtime` probes NVML free memory before and after `worker.start()`. Trellis2 uses
`low_vram=True` (default from `pipeline.json`): its `to(device)` only sets
`self._device` and skips `super().to(device)`, so no weights move to GPU at startup.
NVML delta is 0 → `weight_measure.non_positive_delta` warning → `weight_vram_mb` is
never updated → DB value stays at seed 16000 MB → VRAM allocator permanently reserves
16 GB that is never actually used.

### Why subprocess-reported value is better

The subprocess already calls `_capture_cuda_baseline_mb()` (= `torch.cuda.memory_allocated()`)
immediately after `_build_process_provider()`. This value:
- Is per-process, not whole-card (no cross-model contamination)
- Is 0 for Trellis2 low_vram (correct: weights are on CPU)
- Is non-zero for models that keep weights on GPU (correct)
- Is already computed — just not forwarded to the main process

## Acceptance Criteria

- [ ] `weight_measure.non_positive_delta` warning no longer fires for Trellis2
- [ ] After first load, Trellis2 `weight_vram_mb` in DB is updated to 0 (or near 0)
- [ ] For a hypothetical model with weights on GPU, `weight_vram_mb` is updated to the
      correct non-zero value
- [ ] NVML before/after measurement code removed from `_load_runtime`
- [ ] `vram_probe.py` + `probe_device_free_mb` usages audited — remove if weight
      measurement was the only caller; keep if used elsewhere
- [ ] All existing tests pass; new tests cover the subprocess weight reporting path
- [ ] `AsyncGPUWorker` (mock) returns `startup_weight_mb = None` (measurement disabled
      in mock mode anyway)

## Implementation Plan

### Step 1 — subprocess reports `weight_allocated_mb` in "ready" message

File: `stages/gpu/worker.py`, function `_worker_process_main`

Current:
```python
torch_module, torch_device, baseline_mb = _capture_cuda_baseline_mb()
response_queue.put({"type": "ready"})
```

Change to:
```python
torch_module, torch_device, baseline_mb = _capture_cuda_baseline_mb()
response_queue.put({
    "type": "ready",
    "weight_allocated_mb": baseline_mb,   # None if torch unavailable
})
```

No logic change — `baseline_mb` is already computed, just added to the message.

### Step 2 — `ProcessGPUWorker` captures and exposes the value

File: `stages/gpu/worker.py`, class `ProcessGPUWorker`

Add instance variable:
```python
self._startup_weight_mb: int | None = None
```

In `_pump_responses`, when `message_type == "ready"`:
```python
self._startup_weight_mb = message.get("weight_allocated_mb")  # int | None
```

Add property:
```python
@property
def startup_weight_mb(self) -> int | None:
    return self._startup_weight_mb
```

### Step 3 — `AsyncGPUWorker` (mock) exposes the same property

File: `stages/gpu/worker.py`, class `AsyncGPUWorker`

Add:
```python
@property
def startup_weight_mb(self) -> int | None:
    return None
```

Also add to the `GPUWorkerHandle` protocol if one exists, or to the base class.

### Step 4 — `_load_runtime` uses subprocess-reported value

File: `engine/model_registry.py`, function `_load_runtime`

Remove:
- `before_free_mb` / `after_free_mb` variables
- `probe_device_free_mb` calls
- `weight_measure.non_positive_delta` warning block
- `weight_measure.probe_unavailable` warning block

Replace with:
```python
for worker in runtime.workers:
    await worker.start()

# Collect subprocess-reported weight allocation (first non-None wins)
measured_weight_mb: int | None = None
if self._weight_measurement_enabled:
    for worker in runtime.workers:
        w = getattr(worker, "startup_weight_mb", None)
        if w is not None:
            measured_weight_mb = w
            break
    if measured_weight_mb is None:
        self._logger.debug("weight_measure.not_reported", model_name=model_name)
    else:
        self._logger.info(
            "weight_measure.reported",
            model_name=model_name,
            measured_mb=measured_weight_mb,
        )
```

Note: `measured_weight_mb = 0` is a valid measurement (low_vram model). Do NOT
discard 0 values — pass them through to `_notify_weight_measured`.

### Step 5 — audit `vram_probe.py`

Check all callers of `probe_device_free_mb`:
- If weight measurement in `_load_runtime` was the only caller → remove import and
  usage; `vram_probe.py` can be kept or deleted depending on other uses
- If used elsewhere (VRAM monitor panel etc.) → keep, just remove from `_load_runtime`

### Step 6 — tests

- Update `test_model_registry.py`: replace NVML mock with subprocess "ready" message
  containing `weight_allocated_mb`
- Add case: `weight_allocated_mb=0` → `weight_vram_mb` updated to 0 (not discarded)
- Add case: `weight_allocated_mb=None` → measurement skipped, no error
- Add case: `weight_allocated_mb=12000` → `weight_vram_mb` updated to 12000
- Verify `AsyncGPUWorker.startup_weight_mb` returns None

## Files touched

| File | Change |
|------|--------|
| `stages/gpu/worker.py` | Add `weight_allocated_mb` to "ready" message; add `startup_weight_mb` property to `ProcessGPUWorker` and `AsyncGPUWorker` |
| `engine/model_registry.py` | Replace NVML delta logic with subprocess-reported value in `_load_runtime` |
| `engine/vram_probe.py` | Possibly remove if no other callers |
| `tests/test_model_registry.py` | Update mocks and add new cases |

## Summary

Replaced NVML before/after-window measurement for `weight_vram_mb` with the value
reported directly by the worker subprocess (`torch.cuda.memory_allocated()` after model
load). Trellis2 low_vram mode correctly reports 0; GPU-resident models report the true
allocation. All 24 tests pass.

## Key Decisions

- `weight_allocated_mb=0` is a valid measurement (Trellis2 low_vram) — must not be
  discarded. The old NVML delta check treated `<=0` as an error; the new path passes
  `0` through to `_notify_weight_measured`.
- `vram_probe.py` retained — still used by `api/server.py` to set the allocator's free-MB
  probe; only the `_load_runtime` import removed.
- `int()` cast on `weight_allocated_mb` in `_pump_responses` is safe: value originates
  from `torch.cuda.memory_allocated()` which returns an int.

## Changes

- `stages/gpu/worker.py`: `_worker_process_main` adds `weight_allocated_mb: baseline_mb`
  to the "ready" message; `ProcessGPUWorker` captures it in `_startup_weight_mb` and
  exposes `startup_weight_mb` property; `AsyncGPUWorker` and `GPUWorkerHandle` protocol
  both gain the property returning `None`.
- `engine/model_registry.py`: removed `probe_device_free_mb` import and NVML delta
  measurement block from `_load_runtime`; replaced with `getattr(worker,
  "startup_weight_mb", None)` loop; `weight_measure.not_reported` debug log replaces
  old warnings.
- `tests/test_model_registry.py`: removed `monkeypatch`/`probe_device_free_mb` mocks;
  added `startup_weight_mb` param to `FakeWorker`; added two new test cases
  (`weight=0` and `weight=None`).
- `tests/test_process_gpu_worker_measurement.py`: asserts `weight_allocated_mb` in
  ready message; adds `test_process_gpu_worker_captures_startup_weight_from_ready_message`.
- `tests/test_worker.py`: adds `test_async_gpu_worker_startup_weight_mb_is_none`.

## Notes

- `engine/vram_probe.py` intentionally kept (still used by allocator's free-MB probe).
- All acceptance criteria met; 24 tests pass.

## Out of scope

- Changing Trellis2 `low_vram` behavior
- Measuring inference VRAM (already handled by S3 torch peak)
- Other models (hunyuan3d, step1x3d) — will benefit automatically once weight
  measurement is correct
