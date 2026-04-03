# 改动影响地图

改动某个模块前，查此表确认影响范围和必须跑的测试。

## 核心依赖链

```
api/server.py
  └── engine/async_engine.py
        ├── engine/pipeline.py
        │     ├── engine/sequence.py        (状态机规则)
        │     └── stages/{preprocess,gpu,export}/
        │           └── model/{trellis2,hunyuan3d,step1x3d}/provider.py
        ├── engine/model_registry.py
        │     └── engine/model_scheduler.py
        │           └── storage/model_store.py
        └── storage/task_store.py

storage/artifact_store.py    (被 ExportStage 调用)
storage/api_key_store.py     (被 api/server.py 鉴权逻辑调用)
storage/settings_store.py    (被 api/server.py admin 设置接口调用)
```

## 按模块：改动 → 影响范围 → 必跑测试

| 改动模块 | 直接影响 | 间接影响 | 必跑测试 |
|---------|---------|---------|---------|
| `api/server.py`（路由/鉴权/Schema） | 所有 API 调用方（前端+外部） | — | `test_api.py` |
| `api/schemas.py` | `api/server.py` + 前端类型 | 所有依赖 API 响应的前端页面 | `test_api.py` |
| `engine/async_engine.py` | 任务提交/轮询/SSE/webhook 全流程 | — | `test_api.py` + `test_pipeline.py` |
| `engine/pipeline.py` | stage 编排、崩溃恢复 | — | `test_pipeline.py` + `test_api.py` |
| `engine/sequence.py` | 状态机迁移规则 | pipeline + async_engine 所有状态判断 | `test_pipeline.py` + `test_api.py` |
| `engine/model_registry.py` | 模型加载/卸载/wait_ready | model_scheduler | `test_model_registry.py` |
| `engine/model_scheduler.py` | 多模型配额/LRU 淘汰 | model_registry 触发时机 | `test_model_scheduler.py` |
| `model/base.py`（Protocol） | 所有 Provider 实现 | stages/gpu/stage.py | `test_api.py`（全量） |
| `model/{name}/provider.py` | 对应 Provider 的推理/导出 | ExportStage | `test_api.py`（该 provider 相关用例） |
| `stages/preprocess/stage.py` | 图片预处理逻辑 | — | `test_pipeline.py` |
| `stages/gpu/stage.py` | GPU 推理执行 | — | `test_pipeline.py` + `test_scheduler.py` |
| `stages/gpu/scheduler.py` | GPU slot 调度 | — | `test_scheduler.py` |
| `stages/gpu/worker.py` | GPU worker 封装 | — | `test_worker.py` |
| `stages/export/stage.py` | GLB 导出 + artifact 发布 | artifact_store | `test_pipeline.py` |
| `stages/export/preview_renderer_service.py` | 预览图生成子进程 | — | `test_preview_renderer_service.py` |
| `storage/task_store.py` | 任务持久化 + 事件流 | async_engine/pipeline 的所有状态写入 | `test_task_store.py` + `test_api.py` |
| `storage/model_store.py` | 模型定义 CRUD | model_scheduler | `test_model_store.py` |
| `storage/api_key_store.py` | Key 鉴权 | api/server.py 所有需鉴权路由 | `test_api_key_store.py` + `test_api.py` |
| `storage/settings_store.py` | 系统设置读写 | admin settings API | `test_settings_store.py` |
| `storage/artifact_store.py` | artifact 读写/发布 | ExportStage + artifacts API | `test_pipeline.py` |
| `config.py` | 全局配置字段 | 所有读取 config 的模块 | 全量 `pytest tests -q` |
| `web/src/lib/api.ts` | 用户侧 API client | 所有用户侧页面 | `npm run build` |
| `web/src/lib/admin-api.ts` | Admin API client | 所有 Admin 页面 | `npm run build` |
| `web/src/lib/viewer.ts` | Three.js 渲染器 | `three-viewer.tsx` → Viewer 页 + Generate 页 | `npm run build` |

## 高风险改动（必须全量测试）

以下改动影响面大，必须跑 **全量测试** `python -m pytest tests -q`：

- `engine/sequence.py`：状态机是整个系统的核心，任何状态迁移规则变化都影响 pipeline、engine、API
- `config.py`：全局配置，影响所有模块的初始化
- `model/base.py`：Provider Protocol，所有 Provider 实现必须同步
- `storage/task_store.py`：任务状态持久化，数据库 schema 变化影响全量

## API Contract 变更（需要额外检查）

改动以下内容时，**前端也需要同步更新**：

- `api/schemas.py` 中的响应字段 → 检查 `web/src/lib/api.ts` 和 `admin-api.ts`
- `/v1/tasks` 响应新增/删除字段 → 检查前端所有用到 `task` 对象的页面
- `/api/admin/models` 响应字段 → 检查 `models-page.tsx`
- SSE 事件格式变化 → 检查 `generate-page.tsx` 的 SSE 消费逻辑
