# Admin Panel 全量真实化
Date: 2026-03-21
Status: done

## Goal
将 Admin 5 个页面（Dashboard / Tasks / Models / API Keys / Settings）从纯 mock 数据切换到真实后端 API，实现完整的管理功能。

## 总体设计

### 原则
1. 前端 TypeScript 类型尽量复用现有 `admin-mocks.ts` 的接口定义
2. 后端 API 返回格式匹配前端类型，减少前端改动量
3. 当前不可用的数据（如 GPU 温度、多节点）返回合理默认值，不硬编 fake 数据
4. 所有 admin API 统一用 `require_admin_token` 鉴权

### 后端 API 契约

#### 1. Dashboard — `GET /api/admin/dashboard`
```json
{
  "stats": [
    {"key": "activeTasks", "value": 3},
    {"key": "queued", "value": 1},
    {"key": "completed", "value": 42},
    {"key": "failed", "value": 2}
  ],
  "gpu": {
    "model": "N/A",
    "utilization": 0,
    "vramUsedGb": 0, "vramTotalGb": 0,
    "temperatureC": 0, "powerW": 0, "fanPercent": 0,
    "cudaVersion": "", "driverVersion": "",
    "activeJobs": 1,
    "avgLatencySeconds": 186
  },
  "recentTasks": [...],
  "workers": [
    {
      "id": "worker-0",
      "deviceId": "0",
      "status": "idle" | "busy",
      "currentTaskId": null
    }
  ]
}
```
数据来源：`task_store` 聚合查询 + `engine` 运行时状态 + `model_registry` worker 状态。
GPU 硬件信息（温度、VRAM 等）v0.1 返回零值，v0.2 可接入 pynvml。
`nodes` 字段替换为 `workers`（当前单机，展示 GPU worker 列表）。

#### 2. Tasks — `GET /api/admin/tasks` (增强已有)
已有端点，增加：
- 查询参数：`status` 过滤、`key_id` 过滤（已有）
- 新端点 `GET /api/admin/tasks/stats` 返回聚合统计：
```json
{
  "overview": [
    {"key": "throughput", "value": 14.2, "unit": "/h"},
    {"key": "latency", "value": 186, "unit": "s"},
    {"key": "active", "value": 3}
  ],
  "countByStatus": {
    "queued": 1, "preprocessing": 0,
    "gpu_queued": 0, "gpu_ss": 0, "gpu_shape": 1, "gpu_material": 0,
    "exporting": 0, "uploading": 0,
    "succeeded": 42, "failed": 2, "cancelled": 0
  }
}
```

#### 3. Models — 完整 CRUD
**新 DB 表 `model_definitions`：**
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | 如 "trellis2-4b" |
| provider_type | TEXT | "trellis2" \| "hunyuan3d" |
| display_name | TEXT | "TRELLIS2 Large" |
| model_path | TEXT | HF ID 或本地路径 |
| is_enabled | BOOLEAN | 是否启用 |
| is_default | BOOLEAN | 是否为默认模型（唯一） |
| min_vram_mb | INTEGER | 最低 VRAM 需求 |
| config_json | TEXT | provider 特定参数 JSON |
| created_at | TEXT | ISO 时间戳 |
| updated_at | TEXT | ISO 时间戳 |

**API 端点：**
- `GET /api/admin/models` — 列出所有模型 + 运行时状态
- `POST /api/admin/models` — 注册新模型
- `GET /api/admin/models/{id}` — 单个模型详情
- `PATCH /api/admin/models/{id}` — 更新（启用/禁用/设为默认/改配置）
- `DELETE /api/admin/models/{id}` — 删除模型定义

#### 4. API Keys — 已有后端，前端接入
后端已有完整 CRUD（`/api/admin/keys` + `/api/admin/privileged-keys`）。
增加：
- `last_used_at` 字段（在 `validate_token` 时更新）
- `request_count` 字段（原子递增）
- `GET /api/admin/keys/stats` — 汇总统计

#### 5. Settings — `GET/PATCH /api/admin/settings`
**新 DB 表 `system_settings`：**
| 列 | 类型 |
|---|---|
| key | TEXT PK |
| value | TEXT (JSON) |
| updated_at | TEXT |

Settings 分两层：
- 启动时从 env var 读入默认值（`ServingConfig`）
- DB `system_settings` 表可覆盖部分可热更新的设置
- `GET` 返回合并后的当前生效值
- `PATCH` 写入 DB，可热更新的设置立即生效

可热更新的设置（v0.1）：
- `rate_limit_concurrent`、`rate_limit_per_hour`
- `queue_max_size`
- `webhook_timeout_seconds`

不可热更新的（需要重启）：
- `provider_mode`、`model_provider`、`model_path`
- `artifact_store_mode`
- `database_path`

### 前端改造

每个 admin 页面的 hook（`use-*-data.ts`）从返回 mock 数据改为调用真实 API。
共享 API client 扩展（`lib/api.ts` 或新建 `lib/admin-api.ts`）。
类型定义从 `admin-mocks.ts` 抽取到 `types/admin.ts`。

## 并行任务拆分

### 后端 Stream A — Models（新文件）
- 新建 `storage/model_store.py`
- `api/server.py` 增加 Models CRUD endpoints
- 启动时从 DB 读 enabled models → 注册到 ModelRegistry
- 测试

### 后端 Stream B — Dashboard + Tasks Stats
- `storage/task_store.py` 增加聚合查询方法
- `api/server.py` 增加 dashboard + tasks/stats endpoints
- 测试

### 后端 Stream C — API Keys 增强 + Settings
- `storage/api_key_store.py` 增加 last_used_at / request_count
- 新建 `storage/settings_store.py`
- `api/server.py` 增加 settings + keys/stats endpoints
- 测试

### 前端 Stream D — 所有 admin 页面
- 新建 `lib/admin-api.ts`
- 抽取类型到 `types/admin.ts`
- 改造 5 个 `use-*-data.ts` hooks
- 适配页面组件（如果 API 返回格式有差异）

### 文件冲突分析
- Stream A/B/C 都需改 `api/server.py` → **串行合并**（或各自写独立路由模块）
- Stream A/B/C 改不同的 store 文件 → **可并行**
- Stream D 依赖 API 设计 → **后端先行，前端跟进**

## 验收标准
- 5 个 admin 页面全部显示真实数据（mock 模式下有 mock 任务数据即可）
- Models CRUD 完整可用
- Settings 可热更新支持的项
- API Keys 展示使用量
- 后端测试全部通过，无回归
