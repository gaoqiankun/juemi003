# 关键决策日志

> 记录影响调试和开发判断的重要行为变更，按时间倒序。
> AI Coder 完成任务后，若有影响其他模块行为的变更，在此追加一条。

---

## 2026-03-25

- **HunYuan3D real provider 改为仓库内 pipeline**：`model/hunyuan3d/provider.py` 不再运行时 import 外部 `hy3dgen`，统一切换为 `model/hunyuan3d/pipeline/{shape,texture}.py` 的自维护入口类；mock provider 与 BaseModelProvider 接口保持不变。（plan: 2026-03-25-hunyuan3d-pipeline-internalization.md）

## 2026-03-24

- **`wait_ready` 改为轮询**：模型未加载时不再立即 raise，改为轮询等待调度器触发加载。相关文件：`engine/model_registry.py`。（plan: 2026-03-24-model-registry-wait-ready-polling.md）

- **`on_model_loaded` 后补扫 pending 模型**：模型加载完成后自动触发一次 `_startup_scan_queued_models()`，避免"加载请求丢失"窗口。相关文件：`engine/model_scheduler.py`。（plan: 2026-03-24-model-scheduler-on-model-loaded-rescan.md）

## 2026-03-23

- **调度器启动扫描**：服务启动时自动扫描 QUEUED 任务并触发模型预热，不再需要手动触发。相关文件：`engine/model_scheduler.py`。（plan: 2026-03-23-scheduler-startup-scan.md）

- **模型路径从 DB 读取**：模型文件路径改为从 `model_definitions` 表读取，不再依赖 config.py 硬编码。相关文件：`storage/model_store.py`、`engine/model_registry.py`。（plan: 2026-03-23-model-path-from-db.md）
