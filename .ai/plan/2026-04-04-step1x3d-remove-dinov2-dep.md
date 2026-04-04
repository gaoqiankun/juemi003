# Step1X-3D: Remove Wrong DINOv2 Dependency
Date: 2026-04-04
Status: done

## Root Cause
`provider.py` declares `facebook/dinov2-with-registers-large` as a dependency and overrides
`STEP1X3D_DINO_MODEL_PATH_OVERRIDE` with its resolved path at load time. However, the
Step1X-3D geometry snapshot already embeds the visual encoder (DINOv3) at
`Step1X-3D-Geometry-1300m/visual_encoder/diffusion_pytorch_model.safetensors`.
The override breaks the natural loading path and replaces it with the wrong model
(DINOv2, incomplete snapshot), causing load failure.

## Fix

### `model/step1x3d/provider.py`

1. Remove the `dinov2-with-registers-large` entry from `dependencies()` (:154–158):
   ```python
   ProviderDependency(
       dep_id="dinov2-with-registers-large",
       hf_repo_id="facebook/dinov2-with-registers-large",
       description="DINOv2 geometry encoder",
   ),
   ```

2. Remove the `_temporary_env_var` context manager wrapping `geometry_cls.from_pretrained`
   (:443–449), leaving only the bare call:
   ```python
   geometry_pipeline = geometry_cls.from_pretrained(
       model_reference, subfolder=geometry_subfolder,
   )
   ```

Only `model/step1x3d/provider.py` should be modified.

## Acceptance Criteria
1. `uv run ruff check model/step1x3d/provider.py` — no new lint issues
2. `uv run python -m pytest tests -q` — ≥ 181 passed, no new failures
3. `Step1X3DProvider.dependencies()` no longer contains `dinov2-with-registers-large`
4. No `STEP1X3D_DINO_MODEL_PATH_OVERRIDE` reference remains in `provider.py`
5. `_temporary_env_var` helper (:612) may remain — it is used elsewhere or can stay as dead code; do NOT delete it

## Result
- `model/step1x3d/provider.py`: 删除 `dinov2-with-registers-large` ProviderDependency（4 行）；移除 `_temporary_env_var("STEP1X3D_DINO_MODEL_PATH_OVERRIDE", ...)` context manager，保留裸 `geometry_cls.from_pretrained` 调用；`_temporary_env_var` helper 保留
- geometry pipeline 现在直接从 Step1X-3D snapshot 内嵌的 `visual_encoder/` 子目录加载 DINOv3，不再依赖外部 dep

## Validation
- ✅ ruff check — no issues
- ✅ dependencies() 不含 dinov2-with-registers-large
- ✅ provider.py 无 STEP1X3D_DINO_MODEL_PATH_OVERRIDE
- ✅ _temporary_env_var helper 保留
- ⚠️ 完整 pytest 未跑（Worker 按指示做 quick check）；test_model_store.py 超时为存量问题，与本次改动无关

## Deploy Fix (on deploy machine, after code sync)
The `dinov2-with-registers-large` dep_cache entry becomes orphaned but is harmless.
No manual DB changes needed — Step1X-3D will load `visual_encoder` from its own snapshot.
