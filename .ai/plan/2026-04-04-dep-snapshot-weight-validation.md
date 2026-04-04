# Dep Snapshot Weight Validation Fix
Date: 2026-04-04
Status: done

## Goal
防止 dep_cache 将只含 config 文件、缺少模型权重的 HuggingFace snapshot 标记为 `done`，导致运行时加载失败（复现：Step1X-3D DINOv2 加载报 "no file named pytorch_model.bin / model.safetensors…"）。

## Root Cause
- `migrate_dep_cache.py` 使用 `snapshot_download(..., local_files_only=True)` 探测缓存，找到 snapshot 后只通过 `_directory_has_entries`（目录非空）判断完整性，将只有 config 文件的不完整 snapshot 标记为 `done`
- `weight_manager._download_dep` 同样只做目录非空检查，若 snapshot_download 返回的目录缺少权重，不会报错

## Fix

### 1. `engine/weight_manager.py`
新增 `_snapshot_has_model_weights(path: Path) -> bool`，检查目录树下是否存在至少一个匹配以下 glob 的文件：
- `*.safetensors`
- `pytorch_model*.bin`
- `model.ckpt*`
- `tf_model.h5`
- `flax_model.msgpack`

在 `_download_dep` 的 `_directory_has_entries` 检查之后，追加 `_snapshot_has_model_weights` 检查；失败则 raise `ValueError("downloaded dependency has no model weights: {hf_repo_id}")`。

### 2. `scripts/migrate_dep_cache.py`
在标记依赖为 `done` 之前，加入同样的权重文件检查（复用相同逻辑或内联 glob）；检查失败则标记为 `pending`，并在汇总中报告。

## Acceptance Criteria
1. `uv run ruff check engine/weight_manager.py scripts/migrate_dep_cache.py` 无新增 lint 问题
2. `uv run python -m pytest tests -q` 保持 ≥ 181 passed，不新增 failure
3. `_download_dep` 在 snapshot 无权重文件时抛出含 "no model weights" 的 ValueError
4. `migrate_dep_cache.py --dry-run` 对缺少权重文件的 snapshot 输出 `pending`（而非 `ready`）
5. 不改动其他文件；不修改数据库 schema

## Result
- `engine/weight_manager.py`: 新增 `_snapshot_has_model_weights`（:504），在 `_download_dep`（:215）的目录非空检查后追加权重文件校验；无权重时抛 `ValueError("downloaded dependency has no model weights: ...")`（:226）
- `scripts/migrate_dep_cache.py`: 迁移时对 config-only snapshot 标记 `pending` 而非 `done`（:60/:96）；汇总新增 `no_model_weights` 计数（:144）；修复 `model_definitions` 表不存在时返回值一致性（:83）

## Validation
- ✅ `uv run ruff check engine/weight_manager.py scripts/migrate_dep_cache.py` — 无新增问题
- ✅ `uv run python -m pytest tests -q` — 1 failed, 181 passed（存量失败）
- ✅ `_download_dep` config-only snapshot → ValueError 含 "no model weights"
- ✅ `migrate_dep_cache.py --dry-run` config-only snapshot → pending，输出 `ready=0 pending=1 no_model_weights=1`

## Deployment Fix (manual, on deploy machine)
在运行代码修复前，需在 lab 机器上重置已损坏的 dep_cache 条目：
```sql
UPDATE dep_cache SET download_status='pending', resolved_path=NULL
WHERE dep_id='dinov2-with-registers-large';
```
然后从 Admin 面板重新触发 step1x3d 的权重下载。
