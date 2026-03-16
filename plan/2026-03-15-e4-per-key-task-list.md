# E4 · Per-key 任务列表
Date / Status: 2026-03-15 / done / Commits: uncommitted

## Goal
每个 API Key 能查询自己提交的任务历史，Web 页面从服务端拉取任务列表，替换 localStorage 本地历史。

## Key Decisions

### 数据库
- `tasks` 表新增 `key_id TEXT` 列，存提交该任务的 key_id
- 已有数据 `key_id` 为 NULL（向后兼容，不影响现有任务查询）
- 用 `ALTER TABLE ... ADD COLUMN` 做迁移，服务启动时自动执行

### 鉴权层改造
- `require_bearer_token` 改为返回 `key_id: str | None`（DB key 返回对应 key_id，env var API_TOKEN 返回 None）
- `ApiKeyStore.validate_token(token)` 改为返回 `key_id | None`（None 表示 token 无效）

### 新端点
- `GET /v1/tasks`：返回当前 key 的任务列表，按 `created_at` 倒序，最多返回 50 条
- 响应字段：`task_id, status, created_at, finished_at, artifact_url`（artifact_url 可为 null）
- env var token（key_id=None）可查所有任务（管理方便）

### 任务提交
- `POST /v1/tasks` 提交时从鉴权结果取 key_id，写入 tasks 表

### Web 页面
- 保存 API Key 后 / 页面加载后自动请求 `GET /v1/tasks`
- 展示任务列表：状态、提交时间、成功时显示下载按钮
- 移除 localStorage 任务历史逻辑（config 保存保留）

## Changes
- `storage/task_store.py`
  - `tasks` 表增加 `key_id TEXT`，启动时通过 `PRAGMA table_info + ALTER TABLE ADD COLUMN` 自动迁移
  - 新增 `list_tasks(key_id, limit=50)`，按 `created_at DESC` 返回最多 50 条
- `storage/api_key_store.py`
  - `validate_token(token)` 改为返回 `key_id | None`
- `engine/sequence.py`
  - `RequestSequence` 新增 `key_id`
- `engine/async_engine.py`
  - `submit_task` 接收 `key_id`
  - 新增 `list_tasks`
- `api/server.py`
  - `require_bearer_token` 返回 `key_id: str | None`
  - legacy `API_TOKEN` 映射到 `key_id=None`
  - `POST /v1/tasks` 写入 `key_id`
  - 新增 `GET /v1/tasks`
- `api/schemas.py`
  - 新增 `TaskSummary`、`TaskListResponse`
- `static/index.html`
  - 删除 localStorage 任务历史依赖，改为页面加载 / 保存 API Key / 保存 baseUrl 后请求 `GET /v1/tasks`
  - 任务列表按服务端历史展示，未终态任务自动重连
- `tests/test_api.py`
  - 新增每 key 任务隔离测试
  - 新增 legacy token 可见全量任务测试
  - 新增任务列表 50 条上限与旧表自动迁移测试

## Notes
- key_id=None 的 env var token 查全量任务，便于管理调试
- artifact_url 直接返回现有的 result_url（可能是 presign URL，有 TTL）
- 不做分页，50 条够用
- 验证命令：`python -m pytest tests -q`
