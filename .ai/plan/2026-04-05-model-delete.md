# Model Delete + Storage Management
Date: 2026-04-05
Status: done

## Goal

1. 删除模型只清 DB 记录，磁盘不动
2. 实现存储管理：孤儿缓存检测 + 磁盘告警 banner + Settings 页 Storage 卡片

## 设计决策

- **A. 磁盘清理**：删模型时不清磁盘，统一到 Storage 管理清理
- **B. Dep 实例**：删主模型时只删 `model_dep_requirements`，dep 实例 DB 记录保留（dep 实例的磁盘也保留，等待 Storage 页显示为孤儿后用户主动清理）
- **C. 运行时**：删主模型 DB 前先调 `unload()`（如已加载）
- **孤儿检测**：扫描 `cache_dir/`（主模型）和 `cache_dir/deps/`（dep），对比 DB 中所有 `resolved_path`（`weight_source != 'local'`），不在引用集内的目录 = 孤儿
- **告警阈值**：磁盘剩余 < 20 GB（硬编码，不做 UI 配置）
- **清理范围**：仅批量清孤儿（`DELETE /api/admin/storage/orphans`），本版不做 per-entry delete

## 文件变更

### 后端

**`storage/model_store.py`**
- 新增 `get_all_resolved_paths() -> list[str]`：返回所有 `weight_source != 'local'` 且 `resolved_path IS NOT NULL` 的 resolved_path

**`storage/dep_store.py`**（`DepInstanceStore` 类）
- 新增 `get_all_resolved_paths() -> list[str]`：同上，针对 dep_instances 表

**`engine/weight_manager.py`**
- 新增 `async get_storage_stats() -> dict`
  - `shutil.disk_usage(cache_dir)` 获取磁盘总量/已用/剩余
  - 扫描 `cache_dir/` 和 `cache_dir/deps/` 下所有子目录，计算各目录大小（`shutil.disk_usage(d).used`）
  - 对比 DB resolved_paths 集合，识别孤儿目录
  - 返回：`{ disk_free_bytes, disk_total_bytes, cache_bytes, orphan_bytes, orphan_count }`
- 新增 `async clean_orphans() -> dict`
  - 复用孤儿检测逻辑，`shutil.rmtree` 删孤儿目录
  - 返回：`{ freed_bytes, count }`

**`api/server.py`**
- `delete_model` 端点增强：删 DB 前先通过 `model_registry.unload(model_id)` 卸载（如已加载）
- 新增 `GET /api/admin/storage/stats` → 调 `weight_manager.get_storage_stats()`
- 新增 `DELETE /api/admin/storage/orphans` → 调 `weight_manager.clean_orphans()`

### 前端

**`web/src/lib/admin-api.ts`**
- 新增 `getStorageStats(): Promise<StorageStats>`
- 新增 `cleanOrphans(): Promise<{ freed_bytes: number; count: number }>`
- 新增 `StorageStats` type

**`web/src/components/layout/admin-shell.tsx`**
- mount 时 fetch `getStorageStats()`，clean 后刷新
- 当 `disk_free_bytes < 20 * 1024 ** 3` 时，在 header 下方渲染告警 bar：
  "磁盘剩余 X GB，有 Y GB 孤儿缓存可释放 [立即清理]"
- 点击"立即清理"→ 调 `cleanOrphans()` → 刷新 stats → 无孤儿时自动隐藏 bar

**`web/src/pages/settings-page.tsx`**
- 在现有 settings sections 之后追加一个独立 `<Card>` Storage 区块（不走 settings JSON schema，手写）
- 显示：磁盘使用进度条（used/total）、缓存大小、孤儿大小
- [清理孤儿] 按钮（无论是否告警都显示）
- 数据共用 admin-shell 已有 fetch，通过 context 或 props 传入；若结构不便，settings 页单独 fetch 一次

**`web/src/i18n/`**（zh + en）
- `storage.diskUsage`: "磁盘使用" / "Disk Usage"
- `storage.cache`: "缓存" / "Cache"
- `storage.orphaned`: "孤儿缓存" / "Orphaned Cache"
- `storage.cleanOrphans`: "清理孤儿" / "Clean Orphaned"
- `storage.alert`: "磁盘剩余 {{free}}，有 {{orphan}} 可释放" / "{{free}} disk space left, {{orphan}} can be freed"
- `storage.cleaning`: "清理中…" / "Cleaning…"
- `storage.cleaned`: "已释放 {{freed}}" / "Freed {{freed}}"

## Acceptance Criteria

- [ ] 删除 ready 模型：`unload()` 后删 DB，磁盘文件保留，模型列表不再显示
- [ ] 删除 pending 模型：取消下载（已有）+ 删 DB，磁盘不动
- [ ] `GET /api/admin/storage/stats` 返回正确的 disk_free / orphan_bytes / orphan_count
- [ ] 磁盘剩余 < 20 GB 时，admin header 下方显示告警 bar
- [ ] 磁盘充足时，header 无告警 bar
- [ ] 点击"立即清理"后，孤儿目录被删除，bar 消失（如磁盘已充足），stats 更新
- [ ] Settings 页 Storage 卡片显示磁盘使用进度条、缓存大小、孤儿大小
- [ ] Settings 页 [清理孤儿] 按钮可用且清理后更新显示
- [ ] 中英文 i18n 均已添加
- [ ] 重新添加已删除模型（相同 model_id）：现有行为不变（仍会重新下载，缓存复用为未来任务）

## Summary

删除模型只清 DB（`unload()` 后删记录），磁盘不动。新增存储管理：`WeightManager.get_storage_stats()` / `clean_orphans()` + 两个 API 端点；Admin header 在磁盘剩余 < 20 GB 时显示告警 banner；Settings 页新增 Storage 卡片。

## Key Decisions

- 孤儿检测通过扫描 `cache_dir/` 对比 DB `resolved_path` 集合（排除 `local` 来源）
- `_compute_dir_size` 用递归 `rglob` 累加文件大小，跑在 threadpool 避免阻塞
- Settings 页独立 fetch storage stats，不共享 shell context（简化依赖）
- 告警阈值 20 GB 硬编码，不做 UI 配置

## Changes

- `storage/model_store.py`: `get_all_resolved_paths()`
- `storage/dep_store.py`: `get_all_resolved_paths()`
- `engine/weight_manager.py`: `get_storage_stats()`, `clean_orphans()`, `_compute_dir_size()`
- `api/server.py`: `delete_model` 加 `unload()`；新增 `GET /api/admin/storage/stats`、`DELETE /api/admin/storage/orphans`
- `web/src/lib/admin-api.ts`: `StorageStats` type, `getStorageStats()`, `cleanOrphans()`
- `web/src/components/layout/admin-shell.tsx`: 存储告警 banner
- `web/src/pages/settings-page.tsx`: Storage 卡片
- `web/src/i18n/zh-CN.json` + `en.json`: `storage.*` 7 个 key

## Out of scope

- 缓存复用（重新添加时检测已有 cache 跳过下载）
- 阈值 UI 配置
- Per-entry delete
- Artifact / 生成文件存储管理
