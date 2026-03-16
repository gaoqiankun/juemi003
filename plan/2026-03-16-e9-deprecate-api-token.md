# E9 · 弃用 API_TOKEN，新增管理员任务列表
Date / Status: 2026-03-16 / done / Commits: uncommitted

## Goal
移除 API_TOKEN 对 task API 的访问权限，由 ADMIN_TOKEN + 新的 `/admin/tasks` 端点承接管理员需求，
task API 只接受 managed key。

## Key Decisions

### 移除 API_TOKEN 的 task 鉴权
- `require_bearer_token` 不再 fallback 到 `API_TOKEN`
- 只接受 managed key（通过 `ApiKeyStore.validate_token` 验证）
- 未认证请求返回 401；API_TOKEN 也返回 401
- `config.py` 保留 `api_token` 字段（不删，避免破坏已有部署的 .env），但不再使用
- `.env.example` 中 API_TOKEN 加注释标为 deprecated

### 新增 `GET /admin/tasks`
- 鉴权：`require_admin_token`（ADMIN_TOKEN）
- 支持 `?key_id=xxx`（可选，过滤某个 key 的任务）+ cursor 分页（limit/before，复用 CursorPaginationParams）
- 无 key_id 过滤时返回全量任务
- 响应复用 `TaskListResponse`（`CursorPage[TaskSummary]`）

### 权限矩阵（变更后）
| Token | 提交任务 | 查询自己任务 | 查询全量任务 | 管理 Key |
|-------|---------|------------|------------|---------|
| Managed key | ✓ | ✓ | ✗ | ✗ |
| ADMIN_TOKEN | ✗ | ✗ | ✓（/admin/tasks）| ✓ |
| API_TOKEN | ✗ | ✗ | ✗ | ✗ |

## Changes
| 文件 | 变更说明 |
|------|---------|
| `api/server.py` | `require_bearer_token` 移除 API_TOKEN fallback；新增 `GET /admin/tasks` |
| `.env.example` | `API_TOKEN` 加 deprecated 注释 |
| `deploy.sh` heredoc | 已改为 cp，自动同步 |
| `tests/test_api.py` | 移除 legacy token 相关测试；新增 `/admin/tasks` 测试；task API 测试改用 managed key |

## Notes
- `config.py` 保留 `api_token` 字段，不删，避免已有 .env 报错
- mock 模式（测试用）不受影响，mock 时 require_bearer_token 返回 None
- DELETE /v1/tasks/{task_id} 的 key_id=None（管理员）逻辑需检查：ADMIN_TOKEN 不走 require_bearer_token，所以不能删 user 的任务，这是正确的
- **已知遗留**：`/metrics` 端点仍用 `API_TOKEN` 鉴权（AI Coder 自行保留），将在 E10 中作为 token 权限分层改造的一部分统一处理
