# Disable Trellis2 low_vram mode
Date: 2026-04-16
Status: done

## Goal

统一加载行为：模型加载 = 全量上 GPU，无 CPU offloading。暂时关闭 Trellis2 low_vram，下个大版本再统一设计低显存模式。

## Changes

### 1. `model/trellis2/pipeline/pipelines/trellis2_image_to_3d.py:108`
`pipeline.low_vram = args.get('low_vram', True)` → `pipeline.low_vram = False`
不读 pipeline.json 的值，直接强制 False。

### 2. `storage/model_store.py` — _SEED_MODELS Trellis2
`weight_vram_mb: 0` → `weight_vram_mb: 16000`
全量加载，权重常驻 GPU，seed 恢复到合理初始值（测量系统会校准）。

### 3. `model/trellis2/provider.py` — estimate_weight_vram_mb
当前公式 `batch_total * 1.2 * 0.75` 是 resolution-dependent 的，但模型权重大小与 resolution 无关。
改为固定值：`return 16_000`（与 seed 一致，测量后自动校准）。

`estimate_inference_vram_mb` 相应调整：
`total - weight` 中 weight 改用固定值，inference = 额外激活显存，保持 resolution/batch 相关。

### 4. `tests/test_model_store.py`
`assert trellis["weight_vram_mb"] == 0` → `assert trellis["weight_vram_mb"] == 16000`

## Acceptance Criteria

- [ ] Trellis2 加载后 `pipeline.low_vram is False`
- [ ] `_SEED_MODELS` Trellis2 `weight_vram_mb == 16000`
- [ ] `estimate_weight_vram_mb` 返回固定值，不随 resolution 变化
- [ ] 全部测试通过
