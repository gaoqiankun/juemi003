# Cubie · Claude 架构师记忆

> 子仓库：`./gen3d/`  最后更新：2026-03-24
> 产品名：**Cubie**

---

## 项目定位

可私有部署的开源 3D 生成服务（图片 → GLB），对标 Meshy / Tripo3D。
FastAPI 后端 + React 前端，Provider 模式支持多模型切换，SQLite + 文件系统存储。

测试环境：https://gen3d.frps.zhifouai.com

---

## 当前状态（2026-03-25）

测试基线：**163 passed**

| 模块 | 状态 |
|------|------|
| M1 · 品牌 & 开源化基础 | ✅ |
| M2 · Admin Panel（11 轮打磨） | ✅ |
| M2.5 · 用户侧页面（6 轮打磨） | ✅ |
| M3 · HunYuan3D + Step1X-3D | ✅ mock + real 全实现 |
| M3.5 · 推理代码内化（自维护）| ✅ 三个模型全部完成 |
| M4 · 安装体验（Pinokio）| 🔲 |
| M5 · 文档完善 | 🔲 |
| M6 · 发布前 QA | 🔲 |

未完成小项：`deploy.sh` 中 `ADMIN_TOKEN=` 待补（.agent/plan/2026-03-15-e5-compose-admin-upload-env.md）

---

## 功能全景

**用户侧**：Setup（初始配置）→ Generate（上传图/生成/SSE 进度/预览）→ Gallery（历史任务）→ Viewer（3D 查看/下载/删除）

**Admin**：Tasks（任务监控）/ Models（模型管理：注册/加载/启停）/ API Keys（创建/管理）/ Settings（队列上限/速率/HuggingFace）

---

## 核心架构

### 生成任务链路

```
POST /v1/upload → 存磁盘 → 返回 upload://uuid
POST /v1/tasks → 幂等/限流/容量检查 → 写 QUEUED → 触发模型预热
Worker 轮询认领（乐观锁）→ wait_ready → PipelineCoordinator.run_sequence()
  PreprocessStage  下载/解码/归一化 → input artifact
  GPUStage         占 GPU slot → run_batch → progress_cb → SSE 推送
  ExportStage      export_glb → preview.png → publish_artifact → manifest
每次状态变化 → UPDATE tasks + INSERT task_events + 推 SSE queue
任务结束 → webhook（POST，3 次重试）
```

### 任务状态机

```
QUEUED → PREPROCESSING → GPU_QUEUED → GPU_SS → GPU_SHAPE → GPU_MATERIAL
       → EXPORTING → UPLOADING → SUCCEEDED
任意状态 → FAILED / CANCELLED
```

### 崩溃恢复

- QUEUED / PREPROCESSING → 重新入队
- GPU 阶段及之后 → 强制 FAILED（GPU 结果已丢失）

---

## 关键设计决策

| 决策 | 原因 |
|------|------|
| Stage 管线而非单函数 | 崩溃恢复粒度不同；stage_stats 独立计时用于估算等待；错误定位 `failed_stage` 返回给客户端 |
| 所有路由集中在 server.py | AppContainer（11 个对象）闭包捕获，拆文件需依赖注入，复杂度上升；v0.2 重构 |
| Artifact 用文件系统 + manifest | MinIO presigned URL 有过期须动态生成；删除原子性；URL 依赖服务地址，manifest 重建时自愈 |
| LRU + max_tasks_per_slot | 大模型无法多个共存，纯 LRU 导致冷门模型饿死；配额机制实现公平时间片调度 |
| 静态 Bearer token 不用 JWT | 私有部署场景，`secrets.compare_digest` 防时序攻击已够用 |

---

## Provider 状态

| Provider | mock | real |
|---------|:----:|:----:|
| Trellis2 | ✅ | ✅ |
| HunYuan3D-2 | ✅ | ✅ |
| Step1X-3D | ✅ | ✅ |

`Hunyuan3D-2/` 目录在 git 中 untracked，属正常状态。

---

## 技术债

| 项目 | 优先级 |
|------|--------|
| Docker：HF_TOKEN 未透传 / MODEL_DIR 卷无用 / MODEL_PATH 默认值冲突 | v0.1 发布前 |
| deploy.sh 缺 ADMIN_TOKEN= | v0.1 发布前 |
| 取消只支持 gpu_queued，运行中无法取消 | v0.2 |
| GPU 进度（gpu_ss/shape/material）是语义占位 | v0.2 |
| api/server.py 2247 行，路由未拆分（Router 工厂模式方案已设计）| v0.2 |
| async_engine.py worker loop / cleanup 未拆分（时序敏感，需集成测试覆盖）| v0.2 |
| no-explicit-any × 15（TypeScript）| v0.2 |
| C901 复杂度超标 × 8（Python）| v0.2 |
| 模型 Pipeline 自维护 | ✅ 已完成（2026-03-25） |

---

## 暂缓（v0.2）

背景图/HDRI、多机 Worker、Mac Apple Silicon、Launcher GUI

---

## 角色分配速查

写 Prompt 时，根据任务类型指定角色：

| 任务类型 | 角色 | 角色文件 |
|---------|------|---------|
| Python 功能开发、API、engine、model | 后端工程师 | `.agent/roles/backend.md` |
| React/UI、页面、组件、i18n | 前端工程师 | `.agent/roles/frontend.md` |
| Bug 定位与修复 | 调试工程师 | `.agent/roles/debug.md` |
| 跨前后端（必须同时改两侧）| 在 Prompt 里同时指定两个角色文件 | `backend.md` + `frontend.md` |

Prompt 标准格式：
```
你是[角色名]，工作目录是 gen3d/，先读 AGENTS.md，再读 .agent/roles/[role].md。

【上游产出】（无则省略）
- 上一个任务完成的内容、新增接口、关键变更

【任务】
...

【验收标准】
...
```

**并行分配前**：查 `.agent/plan/` 有无 `Status: planning` 的文件，确认待改文件与新任务无交叉，再同时下发。每个 agent 开工时会在 `.agent/plan/` 创建自己的 planning 文件，这是预期行为。

**摩擦记录**：写 Prompt 时感到别扭、协调超出预期、AI Coder 汇报有困惑，随手在 `.agent/friction-log.md` 加一行。每积累 10 条或每 2 周回顾一次，决定是否调整工作流。

**代码健康**：超标文件（> 500 行）由 AI Coder 验收时自动输出，出现在 plan 汇报里；同一文件被提到 ≥ 2 次时安排重构。

---

## 关键文件索引

| 文件/目录 | 说明 |
|----------|------|
| `AGENTS.md` | AI Coder 核心规则 |
| `web/AGENTS.md` | 前端专项规则 |
| `.claude/rules/` | 路径触发规则（frontend / backend） |
| `.claude/skills/` | 可复用任务模板（new-provider / ui-polish） |
| `api/server.py` | 全部路由 + AppContainer |
| `engine/` | 任务引擎（async_engine / pipeline / model_registry / model_scheduler） |
| `model/` | Provider 实现 |
| `stages/` | preprocess / gpu / export |
| `storage/` | 5 个 store |
| `web/src/` | React SPA |
| `.agent/plan/` | 规划日志（archive/ 存历史） |
