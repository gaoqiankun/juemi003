# Hey3D gen3d

Hey3D 的 3D 生成推理服务——接收图片，输出 3D 模型（GLB）。

> ⚠️ 当前处于规划阶段，代码尚未实现。

## 定位

```
iOS / server ──POST /v1/tasks──→ gen3d（推理）──→ webhook 回调
```

## 技术方案

- **API**：FastAPI + uvicorn，端口 18001
- **推理模型**：TRELLIS2（图片 → 3D mesh → GLB）
- **GPU 调度**：每张 GPU 一个独立 Worker 子进程
- **任务持久化**：SQLite
- **产物存储**：MinIO

## 开发计划

| 阶段 | 内容 |
|------|------|
| Phase A | Mock 推理，链路端到端跑通 |
| Phase B | 接入真实 TRELLIS2 + 真实 GLB 导出 |
| Phase C | Prometheus 指标 |
| Phase D | 多机 / 阶段解耦 |

## 文档

- `docs/PLAN.md`：完整架构规划
- `AGENTS.md`：Phase A 构建指南（供 AI Coder 使用）
