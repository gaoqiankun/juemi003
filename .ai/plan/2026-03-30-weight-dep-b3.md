# Weight Dependency B3
Date: 2026-03-30
Status: done
Commits: N/A（按 AGENTS.md 要求不执行 commit）

## Goal
实现 Weight Dependency B3 后端改造：
- `api/server.py` 在 `build_model_runtime` 中解析并注入真实 `dep_paths`
- `stages/gpu/worker.py` 子进程内设置离线环境变量（不影响主进程）
- 新增一次性迁移脚本 `scripts/migrate_dep_cache.py`（支持 `--dry-run`）
- `config.py` 补齐 `HF_HOME` 环境变量读取与默认值

## Planned Files
- `api/server.py`
- `stages/gpu/worker.py`
- `scripts/migrate_dep_cache.py`
- `config.py`
- `.ai/plan/2026-03-30-weight-dep-b3.md`
- `.ai/decisions.md`（如涉及跨模块行为变更）

## Validation Plan
1. `uv run ruff check api/server.py stages/gpu/worker.py scripts/migrate_dep_cache.py`
2. `uv run python -m pytest tests -q`（目标 ≥ 181 passed）
3. `uv run python scripts/migrate_dep_cache.py --dry-run`
4. 代码检查：`build_model_runtime` 不再硬编码 `dep_paths={}`；离线标志仅在子进程设置

## Result
- `api/server.py`
  - 新增 `_resolve_dep_paths(model_id, dep_cache_store, model_dep_store)`：从 `model_dep_requirements` 读取依赖列表，再从 `dep_cache` 校验每个依赖必须 `download_status='done'` 且 `resolved_path` 存在。
  - `build_model_runtime()` 不再硬编码 `dep_paths={}`，改为运行时解析真实依赖路径并传入 `build_gpu_workers(..., dep_paths=dep_paths)`。
- `stages/gpu/worker.py`
  - 在 `_build_process_provider()` 的 `Provider.from_pretrained(...)` 前设置：
    - `HF_HUB_OFFLINE=1`
    - `TRANSFORMERS_OFFLINE=1`
  - 确保离线兜底仅发生在子进程内。
- `scripts/migrate_dep_cache.py`（118 行）
  - 新增一次性迁移脚本，遍历 `download_status='done'` 的模型；
  - 通过各 Provider 的 `dependencies()` 声明，使用 `snapshot_download(..., local_files_only=True)` 探测本地缓存；
  - 命中则写入/更新 `dep_cache` 为 `done`，否则标记 `pending`；
  - 建立 `model_dep_requirements` 关联；
  - 支持 `--dry-run`，并输出汇总 `ready/pending`。
  - 增强健壮性：自动创建数据库父目录；若不存在 `model_definitions` 表则给出 warning 并返回空汇总。
- `config.py`
  - `ServingConfig` 新增 `hf_home: Path = Field(default=Path(\"~/.cache/huggingface\"), alias=\"HF_HOME\")`。
- `.ai/decisions.md`
  - 追加本次跨模块行为变更：运行时依赖就绪校验与子进程离线兜底策略。
- `.ai/friction-log.md`
  - 记录 prompt 路径在工作区根目录与子仓库之间不一致导致的一次定位成本。

## Validation
- `uv run ruff check api/server.py stages/gpu/worker.py scripts/migrate_dep_cache.py`
  - 结果：存在 **6 条存量告警**（`C901` 复杂度与两个 `F841` 未使用变量，均位于历史大函数），本次改动未新增新的 lint 类型告警；新增脚本无独立 lint 问题。
- `uv run python scripts/migrate_dep_cache.py --dry-run`
  - 结果：通过，输出
    - `[WARN] model_definitions table not found; nothing to migrate.`
    - `[DRY-RUN] ready=0 pending=0`
- `uv run python -m pytest tests -q`
  - 结果：`1 failed, 181 passed`
  - 唯一失败：`tests/test_api.py::test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu[asyncio]`（存量失败）。
- 代码检查
  - `api/server.py` 内已无 `dep_paths={}` 硬编码。
  - `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` 仅出现在 `stages/gpu/worker.py` 子进程 provider 构建路径。
