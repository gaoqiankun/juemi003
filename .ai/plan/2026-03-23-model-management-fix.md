# 模型管理逻辑完善
Date: 2026-03-23
Status: done
Commits: N/A（按 AGENTS.md 要求未执行 commit）

## Goal

让多模型真正可用：修复加载失败后无法重试、任务提交与模型就绪解耦、引入 GPU 资源感知的模型调度器防止饥饿。

## Key Decisions

### 1. error 状态允许重试
`ModelRegistry.load()` 中将 guard 从 `{"loading", "ready", "error"}` 改为 `{"loading", "ready"}`。
error 分支重置 event 和 error 字段后继续执行加载流程。
asyncio 单线程，无 await，状态重置是原子的，无并发竞争。

### 2. 任务提交与模型就绪解耦
`POST /v1/tasks` 不再校验 runtime state，任何 enabled 的模型都可接受任务提交。
任务进入 `queued` 状态等待，由调度器负责保证最终被处理。

### 3. runtime state 透出 API
`GET /v1/models` 响应每个 model 加 `runtime_state` 字段（not_loaded / loading / ready / error）。
`UserModelSummary` schema 同步更新。

### 4. ModelScheduler —— GPU 资源感知调度器（新组件）

**职责**：决定什么时候加载哪个模型、什么时候驱逐哪个模型。

**资源上限探测**（启动时一次）：
- 通过 `torch.cuda.mem_get_info()` 或 `nvidia-smi` 获取总 VRAM
- `model_definitions` 表新增 `vram_gb` 字段（float，可为 null 表示未知）
- `max_possible_loaded = floor(total_vram_gb / max(vram_gb of all models))`，作为 `max_loaded_models` 配置的上限

**可配置项**（Admin Settings 页，持久化到 system_settings 表）：
- `max_loaded_models: int`（1 ≤ value ≤ max_possible_loaded，默认 1）
- `max_tasks_per_slot: int`（每个模型连续处理多少任务后变为可驱逐，默认 8）

**调度流程**：

`on_task_queued(model_id)`：
1. 若目标模型已 ready → 无需操作，worker 自然会捡起
2. 若目标模型正在 loading → 等待，不重复触发
3. 若目标模型 not_loaded 或 error：
   - 有空余槽位 → 触发 `registry.load(model_id)`
   - 槽位已满 → 寻找驱逐候选：无 running 任务 且（quota 已超 或 无 pending 任务）的模型，选 LRU
   - 找到候选 → 驱逐（unload）后触发目标模型 load
   - 找不到候选 → 任务继续等待，不做任何操作

`on_task_completed(model_id)`：
1. 该模型累计处理数 +1
2. 若累计数 ≥ `max_tasks_per_slot` 且存在其他模型有 pending 任务 → 将该模型标记为"quota 已超"
3. quota 超出后若有其他模型任务进队，触发上述驱逐流程

`on_model_loaded(model_id)`：重置该模型累计处理数为 0

**模型卸载**（unload）：
- `ModelRegistry` 新增 `unload(model_id)` 方法：释放模型对象（del + gc + torch.cuda.empty_cache），状态重置为 `not_loaded`

### 5. Admin 触发 Load/Retry
新增 `POST /api/admin/models/{id}/load` endpoint（admin auth），直接调用 `scheduler.request_load(model_id)`，立即返回当前 runtime state。
Admin 模型页：not_loaded → "Load" 按钮；error → "Retry" 按钮；loading → 按钮禁用。

### 6. Admin 模型列表展示 runtime state
`GET /api/admin/models` 响应加 `runtime_state` 和 `tasks_processed`（当前 slot 已处理任务数）字段。
loading 状态下前端 poll 间隔收紧到 3s（原 10s）。

### 7. 用户侧 Generate 页模型下拉
对非 ready 模型显示灰色状态标签（不强制禁用，避免影响 mock/dev 环境体验）。

## Changes

**后端**
- `engine/model_registry.py`: 修复 error guard；新增 `unload(model_id)` 方法；新增 `runtime_states()` 批量返回所有模型状态
- `engine/model_scheduler.py`: **新文件**，ModelScheduler 类，实现上述调度逻辑
- `storage/model_store.py`: `model_definitions` 表新增 `vram_gb` 字段（migration）
- `storage/settings_store.py`: 新增 `max_loaded_models`、`max_tasks_per_slot` 设置 key
- `api/server.py`:
  - `GET /v1/models` 加 `runtime_state`
  - `POST /v1/tasks` 去掉 runtime state 校验，改为提交后调 `scheduler.on_task_queued()`
  - `POST /api/admin/models/{id}/load` 新增
  - `GET /api/admin/models` 加 `runtime_state`、`tasks_processed`
  - worker 任务完成后调 `scheduler.on_task_completed()`
- `api/schemas.py`: `UserModelSummary` 加 `runtime_state`；`AdminModelDetail` 加 `runtime_state`、`tasks_processed`
- `config.py`: 新增 `VRAM_DETECTION_ENABLED`（默认 true）
- 收尾修复：
  - `storage/model_store.py` migration 精度修复：`min_vram_mb / 1024.0`
  - `engine/model_scheduler.py` `_normalize_model_name("")` 不再 fallback 到 `"trellis"`
  - `engine/model_registry.py` `_normalize_name("")` 不再 fallback 到 `"trellis"`
  - `api/server.py` `POST /v1/tasks` 空 model 时改为读取 DB 默认模型，不再硬编码 `"trellis"`

**前端**
- `web/src/lib/admin-api.ts`: 新增 `loadModel(id)`；`AdminModel` 类型加 `runtime_state`、`tasks_processed`
- `web/src/hooks/use-models-data.ts`: 新增 `loadModel` action；loading 状态下 poll 3s
- `web/src/pages/models-page.tsx`: Load/Retry 按钮；runtime_state badge；tasks_processed 显示
- `web/src/pages/settings-page.tsx`: 新增 `max_loaded_models`（含上限提示）、`max_tasks_per_slot` 配置项
- `web/src/lib/types.ts`: `UserModelPayload` 加 `runtime_state?: string`
- `web/src/pages/generate-page.tsx`: 模型下拉非 ready 显示灰色状态标签
- i18n: 新增相关 key（en.json + zh-CN.json）

**测试**
- `test_model_registry_retry_after_error`: error 后 load() 可重新触发
- `test_model_registry_unload`: unload 后状态为 not_loaded
- `test_scheduler_auto_load_on_task_queued`: 任务提交触发 auto-load
- `test_scheduler_eviction_lru`: 槽位满时驱逐 LRU 空闲模型
- `test_scheduler_quota_prevents_starvation`: quota 超出后有等待任务时触发驱逐
- `test_scheduler_on_task_queued_is_noop_when_disabled`: mock/disabled 场景调度 no-op
- `test_scheduler_vram_detection_failure_falls_back_to_one_slot`: VRAM 探测失败回退
- `test_admin_model_load_endpoint_returns_runtime_state`: Admin Load endpoint 可用
- `test_admin_settings_patch_updates_scheduler_limits`: 新设置项可更新
- `test_initialize_migrates_vram_gb_using_1024_divisor`: migration 除数验证为 `1024.0`
- `test_scheduler_normalize_model_name_keeps_empty_string`: 空字符串 normalize 行为验证
- `test_model_registry_normalize_name_keeps_empty_string`: 空字符串 normalize 行为验证
- `test_create_task_with_empty_model_uses_default_model_from_store`: 空 model 使用 DB 默认模型

## Notes

- mock 模式下 scheduler 调用 `on_task_queued` 为 no-op，不影响现有测试行为
- VRAM 探测失败（非 CUDA 环境）时 `max_possible_loaded` 回退为 1，不报错
- `vram_gb` 字段为 null 时排除出上限计算（保守策略：只用已知 vram_gb 的模型计算）
- 本轮不动 Docker/依赖问题（P3/P4），那是单独的镜像构建任务
