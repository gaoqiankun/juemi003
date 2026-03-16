# E7 · 任务软删除 + 分页查询
Date / Status: 2026-03-16 / done / Commits: uncommitted

## Goal
用户可删除自己的任务记录，删除时清理 artifact 文件；GET /v1/tasks 支持分页。

## Key Decisions

### 软删除
- `tasks` 表新增 `deleted_at TEXT` 列，启动时自动迁移
- `DELETE /v1/tasks/{task_id}`：设置 `deleted_at = now()`，同时清理 artifact 文件
- `GET /v1/tasks` 过滤 `WHERE deleted_at IS NULL`
- 鉴权：managed key 只能删自己的任务（key_id 匹配），legacy token 可删任意任务
- 已在进行中的任务（非终态）不允许删除，返回 409

### Artifact 文件清理
- 通过已有的 ArtifactStore 抽象执行删除，覆盖 local 和 object store 两种模式
- local 模式：删除 `ARTIFACTS_DIR/{task_id}/` 整个目录
- object store 模式：删除 bucket 下该 task_id 前缀的所有对象
- 文件删除失败不影响软删除本身（记录照样标记 deleted_at），记 warning 日志

### 分页（cursor-based）
- `GET /v1/tasks?limit=20&before=<created_at_iso>`，limit 上限 50，默认 20
- `before` 缺省时返回最新一页
- 响应新增 `next_cursor`（下一页的 before 值，即本页最后一条的 created_at）、`has_more`
- 翻页稳定，新任务进来不影响已有分页结果

## Changes
- `pagination.py`
  - 新增通用 cursor 分页结果模型与默认 limit 常量
- `storage/task_store.py`
  - `tasks` 表新增 `deleted_at` 自动迁移
  - `get_task` / `list_tasks` 默认过滤已删除记录
  - `list_tasks` 改为 `limit + before` cursor 分页，返回 `CursorPageResult`
  - 新增 `soft_delete_task`
- `storage/artifact_store.py`
  - 新增 `delete_artifacts(task_id)`，覆盖 local 和 minio
  - 扩展 object storage client 协议，支持按前缀列举/删除对象
- `engine/sequence.py`
  - `RequestSequence` 增加 `deleted_at`
- `engine/async_engine.py`
  - `list_tasks` 改返回分页结果
  - 新增 `delete_task`，软删除后 best-effort 清理 artifact，失败只记 warning
- `api/schemas.py`
  - 抽出通用 `CursorPage[T]`、`CursorPaginationParams`
  - `TaskListResponse` 复用通用 cursor 分页 schema
- `api/server.py`
  - `GET /v1/tasks` 改为 cursor 分页接口
  - 新增 `DELETE /v1/tasks/{task_id}`
  - managed key 删除时校验 `key_id` 归属
- `static/index.html`
  - 每条任务新增删除按钮
  - 任务列表支持 cursor 翻页和“加载更多”
- `tests/test_api.py`
  - 更新任务列表测试到 cursor 分页结构
  - 新增软删除、409、403、稳定翻页测试
- `tests/test_pipeline.py`
  - 新增 minio artifact 删除测试
- `docs/PLAN.md`
  - 同步 API 文档到 cursor 分页 + 删除接口

## Notes
- 当前实现沿用现有状态枚举，终态为 `succeeded / failed / cancelled`
- artifact 清理是 best-effort，失败只记日志
- 分页用 cursor（before=created_at），翻页结果稳定，不受新任务影响
- 验证命令：`python -m pytest tests -q`
