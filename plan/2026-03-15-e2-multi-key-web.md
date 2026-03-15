# E2 · 多用户 API Key 管理 + Web 测试页升级
Date / Status: 2026-03-15 / done / Commits: none

## Goal
支持多用户通过各自 API Key 使用测试页，Key 由管理员手动生成和停用，
Web 页面升级为可分发的完善版本。

## Key Decisions

### 后端
- 新增 `ApiKeyStore`（独立 storage 类，复用同一个 SQLite 数据库）
  - 表：`api_keys(key_id TEXT PK, token TEXT UNIQUE, label TEXT, created_at TEXT, is_active INTEGER)`
  - token 明文存储（内部工具，不对外暴露原文，创建时只返回一次）
- `require_bearer_token` 改为查 `api_keys` 表（is_active=1），向后兼容：
  若 `API_TOKEN` env var 设置了，也接受该 token（方便旧部署平滑过渡）
- 新增 `ADMIN_TOKEN` env var（config.py），用于保护 `/admin/*` 端点
- 新增管理端点（不走 rate limit、不计并发）：
  - `POST /admin/keys` body: `{label: str}` → 生成随机 token，返回 `{key_id, token, label}`（token 只此一次）
  - `GET /admin/keys` → 返回 `[{key_id, label, created_at, is_active}]`（不含 token）
  - `PATCH /admin/keys/{key_id}` body: `{is_active: bool}` → 启用/停用
- Mock 模式下维持现状（无需 token）

### 前端（单 HTML 文件）
- 顶部固定「API Key」输入区：输入框 + 保存按钮，token 存 localStorage
- 所有 API 请求带 `Authorization: Bearer {token}`，401 时提示 key 无效
- 任务历史：localStorage 存最近 20 条（task_id + 提交时间 + 状态），刷新后可恢复
- 生成完成后显示「下载 .glb」按钮
- UI 风格与现有页面保持一致（配色、圆角、字体）

## Changes
| 文件 | 变更说明 |
|------|---------|
| `storage/api_key_store.py` | 新建，ApiKeyStore 类，CRUD + 初始化建表 |
| `config.py` | 新增 `admin_token: str \| None` |
| `api/server.py` | require_bearer_token 改查 DB；新增 /admin/keys 路由；AppContainer 加 api_key_store |
| `api/schemas.py` | 新增 admin key 请求/响应模型 |
| `static/index.html` | key 输入区、任务历史、下载按钮 |
| `tests/` | 补充 admin 端点 + 多 key 鉴权测试 |
| `README.md` / `docs/PLAN.md` | 同步 `ADMIN_TOKEN` 和多 key 鉴权描述 |

## Notes
- ADMIN_TOKEN 未设置时 /admin/* 端点返回 503（防止裸奔）
- key_id 用 uuid4 hex，token 用 secrets.token_urlsafe(32)
- 历史任务的 artifact URL 可能过期（presign TTL），列表只存 task_id 不缓存 URL
- `python -m pytest tests -q` 结果：`40 passed`
