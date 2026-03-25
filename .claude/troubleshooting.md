# 故障诊断指南

遇到问题时，按症状找对应章节，快速定位根因。

---

## 后端：测试失败

### `test_api.py` 失败

| 症状 | 可能根因 | 排查位置 |
|------|---------|---------|
| provider 相关用例失败 | Provider 接口改了但测试 mock 未同步 | `model/base.py` Protocol vs 测试里的 fake provider |
| schema validation 错误 | `api/schemas.py` 字段变了 | 对比报错字段与 schemas.py 定义 |
| 鉴权相关用例失败 | `api_key_store` 或鉴权中间件改了 | `api/server.py` 的 `require_bearer_token` |
| SSE 相关用例失败 | `task_events` 表结构或事件格式改了 | `storage/task_store.py` 的 `list_task_events` |

### `test_model_scheduler.py` 失败

通常是 `_select_eviction_candidate` 或 `_startup_scan_queued_models` 逻辑改动引起。
重点检查：`_last_used` tick 更新顺序、`_quota_exceeded` 状态的进出条件。

### `test_pipeline.py` 失败

- Stage 执行顺序改了 → 检查 `PipelineCoordinator.run_sequence()`
- 状态迁移不符合预期 → 检查 `engine/sequence.py` 的迁移规则
- artifact 路径断了 → 检查 `stages/export/stage.py` 的 staging → publish 流程

### `test_task_store.py` 失败

多为数据库 schema 变化引起。检查：
1. `task_store.py` 里的 `CREATE TABLE` 语句
2. `claim_next_queued_task` 的乐观锁 UPDATE 条件

---

## 后端：运行时错误

### 模型加载失败 / 一直 `loading` 不变 `ready`

1. 检查 `model_registry.py` 的 `_load_runtime`，看 load task 是否抛异常
2. 检查日志里 `model_registry` 相关的 structlog 输出
3. `wait_ready()` 默认超时 30 分钟，超时前日志会有轮询记录

### 任务卡在 `gpu_queued`

1. GPU slot 是否被占满：检查 `stages/gpu/scheduler.py` 的 slot 状态
2. 模型是否处于 `loading` 状态占位但未 ready：检查 `model_scheduler._max_loaded_models`
3. `on_model_loaded()` 后有没有触发 `_startup_scan_queued_models`

### 任务失败，`failed_stage` 是 `preprocess`

图片下载/解码问题：
- `upload://` URL → 检查 `config.uploads_dir` 目录是否存在
- `http://` URL → 检查网络、超时（默认 15s）、大小限制（默认 10MB）
- 图片格式问题 → 检查 magic bytes 检测逻辑（`stages/preprocess/stage.py`）

### 任务失败，`failed_stage` 是 `export`

1. GLB 导出失败 → 检查 Provider 的 `export_glb()` 返回的 mesh 对象类型
2. artifact 写入失败 → 检查 `config.artifacts_dir` 权限
3. MinIO 模式 → 检查 `OBJECT_STORE_*` 环境变量配置

### Webhook 未触发 / 反复重试

- 检查 `config.allowed_callback_domains`（域名白名单）
- 回调 URL 必须是允许的域名，否则在提交任务时就会 400

---

## 前端：构建失败

### TypeScript 类型错误

- 通常是 `api/schemas.py` 改了但前端类型未同步
- 对照 `web/src/lib/api.ts` 或 `admin-api.ts` 的接口定义

### i18n key 缺失（运行时 key 显示为 raw key）

- 检查 `en.json` 和 `zh-CN.json` key 集合是否一致
- 用 `grep` 查 key 是否在两个文件都存在

### 页面加载空白 / 路由 404

- 检查 `web/src/App.tsx` 路由注册
- 注意 `proof-shots-page` / `reference-compare-page` 故意未挂载路由

---

## Docker / 部署

### Admin HF 面板显示"未连接"

已知问题（技术债）：`HF_TOKEN` 未在 docker-compose.yml 透传。
临时绕过：在 Admin Settings 页手动登录 HuggingFace。

### 模型加载后 VRAM 不够 / 意外被淘汰

1. 检查 `admin/settings` 的 `max_loaded_models` 是否超过 VRAM 上限
2. `max_possible_loaded` 由 `总VRAM / 最大单模型vram_gb` 计算，可在 Admin 设置页查看上限值

### `PROVIDER_MODE=real` 启动后立即崩溃

运行 preflight 检查：
```bash
python serve.py --check-real-env
```
输出 JSON 报告，显示各项环境依赖的检查结果。
