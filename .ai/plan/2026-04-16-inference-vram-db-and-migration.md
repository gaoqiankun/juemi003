# Inference VRAM DB estimate + weight migration
Date: 2026-04-16
Status: done

## Goal

1. inference 预估读取 DB 测量值，不再纯靠公式
2. 修复存量 DB 中 Trellis2 weight_vram_mb=0 的错误值

## Changes

### Fix 1 — inference 预估读 DB (`api/server.py`)

在 `runtime_loader` 闭包中：
- 新增 `_inference_mb_holder: list[int | None]`，初始值读 DB `inference_vram_mb`
- `on_inference_measured`：每次推理测完后更新 holder
- `estimate_inference_vram_mb`：`max(formula, holder)` — DB 有实测值时取较大值（保守）

逻辑：
- DB 无数据时：纯公式（现状不变）
- DB 有数据时：`max(公式, 实测)`，确保不低于历史峰值

### Fix 2 — DB migration (`storage/model_store.py`)

在 `initialize()` 的 schema 迁移后加一条：
```sql
UPDATE model_definitions SET weight_vram_mb = 16000
WHERE id = 'trellis2' AND weight_vram_mb = 0
```
只修 weight=0 的 Trellis2（昨天短暂错误写入的值），不影响其他数据。

## Acceptance Criteria

- [ ] `estimate_inference_vram_mb` 在 DB 有测量值时使用 `max(公式, DB值)`
- [ ] 首次加载（DB 无测量数据）行为不变
- [ ] 存量 DB 中 Trellis2 weight_vram_mb=0 自动修正为 16000
- [ ] 全部测试通过
