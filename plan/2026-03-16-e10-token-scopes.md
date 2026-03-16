# E10 · Token 权限分层（Scoped Privileged Tokens）
Date / Status: 2026-03-16 / done / Commits: none

## Goal
建立清晰的 token 分层体系：ADMIN_TOKEN 只负责创建特权 token，特权 token 各司其职，
彻底移除 API_TOKEN，为 IP 白名单等后续运维能力预留扩展点。

## Key Decisions

### Token 分层

```
ADMIN_TOKEN（env var，只在服务器/运维侧使用）
└── 创建 Privileged Token（存入 DB）
    ├── key_manager scope  → 管理 user key（POST/GET/PATCH /admin/keys）
    ├── task_viewer scope  → 查全量任务（GET /admin/tasks）
    ├── metrics scope      → 读监控数据（GET /metrics）
    └── （预留）service scope → 未来对接其他服务
         └── 创建 User Key（存入 DB，scope=user）
             └── 提交/查询自己的任务
```

### 权限矩阵

| Token | 创建特权 token | 管理 user key | 查全量任务 | 读 metrics | 提交/查任务 |
|-------|--------------|--------------|-----------|-----------|------------|
| ADMIN_TOKEN | ✓ | ✗ | ✗ | ✗ | ✗ |
| key_manager | ✗ | ✓ | ✗ | ✗ | ✗ |
| task_viewer | ✗ | ✗ | ✓ | ✗ | ✗ |
| metrics | ✗ | ✗ | ✗ | ✓ | ✗ |
| user key | ✗ | ✗ | ✗ | ✗ | ✓ |

### DB 结构调整
- `api_keys` 表新增 `scope TEXT NOT NULL`（`user` / `key_manager` / `task_viewer` / `metrics`）
- `api_keys` 表新增 `allowed_ips TEXT`（JSON 数组，NULL 表示不限制），为 IP 白名单预留，本期不做校验逻辑
- 现有 user key 记录迁移：`scope` 默认填 `user`

### 鉴权逻辑调整
- `require_bearer_token`：只接受 `scope=user` 的 key（其余 401）
- `/admin/keys`：改为接受 `scope=key_manager` 的 privileged token
- `GET /admin/tasks`：改为接受 `scope=task_viewer` 的 privileged token
- `GET /metrics`：改为接受 `scope=metrics` 的 privileged token
- ADMIN_TOKEN 鉴权仅用于 `/admin/privileged-keys` 端点

### 新增端点
- `POST /admin/privileged-keys`：ADMIN_TOKEN 鉴权，body `{scope, label, allowed_ips?}`，返回 token
- `GET /admin/privileged-keys`：ADMIN_TOKEN 鉴权，列出所有特权 token（不返回 token 明文）
- `DELETE /admin/privileged-keys/{key_id}`：ADMIN_TOKEN 鉴权，吊销特权 token

### API_TOKEN 彻底退出
- `config.py` 删除 `api_token` 字段
- `.env.example` 删除 `API_TOKEN` 行

## Changes
| 文件 | 变更说明 |
|------|---------|
| `storage/api_key_store.py` | 已加 `scope` / `allowed_ips` 字段、auto-migration、privileged key CRUD、按 scope 校验 token |
| `api/server.py` | 已新增 `/admin/privileged-keys` CRUD；`/admin/keys`、`/admin/tasks`、`/metrics` 全改为 scope 鉴权 |
| `api/schemas.py` | 已补 privileged key request/response schema |
| `config.py` | 已删除 `api_token` 字段 |
| `.env.example` | 已删除 `API_TOKEN` 行 |
| `serve.py` | 已通过 uvicorn 参数启用 `proxy_headers=True` 和 `forwarded_allow_ips="*"` |
| `docker-compose.yml` / `deploy.sh` / `README.md` / `docs/PLAN.md` / `CLAUDE.md` | 已同步移除 `API_TOKEN` 文档与部署说明，补 token 分层说明 |
| `tests/test_api.py` | 已更新 admin / metrics / user key 测试，并补 legacy `api_keys` 迁移用例 |

## Notes
- `allowed_ips` 本期只存不校验，后续单独加校验中间件
- privileged token 与 user key 存同一张表，用 `scope` 区分
- 现有 user key 不受影响，auto-migration 自动补 `scope='user'`
- ADMIN_TOKEN 不再直接鉴权任何业务端点，只用于管理 privileged token
- 验收：`python -m pytest tests -q` -> `61 passed`
- **IP 白名单安全要求**：
  - `X-Forwarded-For` 可被客户端伪造，**不能用于 IP 白名单校验**
  - 应使用 `X-Real-IP`：nginx 以 `proxy_set_header X-Real-IP $remote_addr` 设置，覆盖客户端传入值，不可伪造
  - 流量必须经过 nginx 才可信；frps 直连绕过 nginx，IP 不可信
  - 生产启用 IP 白名单前须：① 防火墙关闭 frps 直连端口；② 所有流量走 nginx → frps → frpc → gen3d；③ 代码从 `X-Real-IP` header 取 IP 做校验
  - IP 白名单校验逻辑本期只实现存储，不做运行时校验，等 nginx 路径收口后再开启
