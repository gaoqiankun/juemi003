# Hey3D gen3d · Claude 架构师记忆

> 子仓库：`/Users/gqk/work/hey3d/gen3d/`（独立 git 仓库）

---

## 规划日志

历次规划和执行记录在 `plan/`（当前有 Phase A 架构规划），完成后随代码一起提交。

---

## 当前状态

**代码未实现，处于规划阶段。**

仓库内容：
- `docs/PLAN.md`：完整架构规划（必读，是设计基准）
- `docs/PLAN.bak.md`：旧版规划备份
- `AGENTS.md`：Phase A 构建指南（给 AI Coder 的执行说明）

---

## 定位

gen3d 是 3D 生成推理服务，接收图片 → 生成 3D 模型（GLB）。

```
iOS/server ──POST /v1/tasks──→ gen3d
gen3d ──生成完成──→ 回调 callback_url（webhook）
```

---

## 技术选型（规划）

| 层 | 技术 |
|---|---|
| API | FastAPI + uvicorn |
| 推理 | TRELLIS2（`Trellis2ImageTo3DPipeline`） |
| GPU 调度 | multiprocessing（每 GPU 一个 Worker 子进程） |
| 批次形成 | FlowMatchingScheduler（max_batch + deadline 策略） |
| 存储 | SQLite（任务状态）+ MinIO（产物） |

---

## 实现阶段规划

| 阶段 | 目标 |
|------|------|
| Phase A | Mock 推理，整个链路端到端跑通 |
| Phase B | 接入真实 TRELLIS2 权重，真实 GLB 导出 |
| Phase C | Prometheus 指标 + Grafana 看板 |
| Phase D | 阶段解耦、多机 Worker |

---

## 下一步

启动 Phase A 实现前，先让 AI Coder 读 `docs/PLAN.md` 和 `AGENTS.md`。
