# artifact_store 模块化拆分重构
Date: 2026-03-25
Status: done

Date / Status: 2026-03-25 / done / Commits: N/A（按 AGENTS.md 要求未执行 commit）
## Goal
将 `storage/artifact_store.py` 从单文件拆分为 facade + 6 个子模块，保持现有对外 import 路径不变并通过测试。

## Key Decisions
- `artifact_types.py` 作为底层类型模块，不反向依赖 `artifact_store.py`。
- facade 仅保留编排逻辑和兼容导出，业务细节下沉到 backend/manifest/utils。
- 对外符号（`ArtifactStore` / `ArtifactStoreOperationError` / `ObjectStorageStreamResult` / `build_boto3_object_storage_client`）继续从 `storage/artifact_store.py` 导出。

## Changes
- 已新增：`storage/artifact_types.py`（异常/Protocol/数据结构）
- 已新增：`storage/object_storage_client.py`（Boto3 client + builder）
- 已新增：`storage/artifact_local_backend.py`（local publish/list/get/delete）
- 已新增：`storage/artifact_minio_backend.py`（minio publish/download/stream/delete）
- 已新增：`storage/artifact_manifest.py`（manifest 读写/原子替换/本地 URL 规范化）
- 已新增：`storage/artifact_utils.py`（文件名安全/URL 解析/type-content-type 推断）
- 已改造：`storage/artifact_store.py` 为 facade，当前 `160` 行（≤ 160）

## Notes
- 开工前基线：`.venv/bin/python -m pytest tests -q` → `163 passed`
- 拆分后验收：
  - `.venv/bin/python -m pytest tests -q` → `163 passed`
  - `.venv/bin/ruff check storage/artifact_store.py storage/artifact_types.py storage/object_storage_client.py storage/artifact_local_backend.py storage/artifact_minio_backend.py storage/artifact_manifest.py storage/artifact_utils.py` → All checks passed
  - `.venv/bin/ruff check . --statistics` → 51 个存量问题（E402/C901/F401/F841），无本次新增问题
