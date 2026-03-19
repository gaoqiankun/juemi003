# Hey3D gen3d · Claude 架构师记忆

> 子仓库：`/Users/gqk/work/hey3d/gen3d/`（独立 git 仓库）
> 最后更新：2026-03-19

## 规划日志

- 历史规划和执行记录在 `plan/`
- `plan/2026-03-19-web-ui-product-reference-alignment.md`：Status = done，已随 E14 提交（59a09f5）

## 当前状态（2026-03-19）

- `gen3d` 已是可运行的 Python/FastAPI 3D 生成服务，Phase A/B/C 全部完成
- 当前测试基线：`python -m pytest tests -q` 为 `71 passed`
- Provider：
  - `mock`：`MockTrellis2Provider`
  - `real`：`Trellis2Provider`
  - `hunyuan3d`：占位，未实现
- Artifact backend：`local` / `minio`
- 对外功能已具备：任务提交、任务查询、SSE 事件流、取消、终态 webhook、artifacts 查询
- 部署材料已齐：`docker/Dockerfile`、根目录 `docker-compose.yml`、`deploy.sh`
- 真实 TRELLIS2 链路已在 GPU 服务器跑通
- **Phase C 新增能力（已上线）**：C1 安全、C2 可靠性、C3 多卡并发、C4 可观测性、C5 Web UI
- E12（2026-03-18）：engine.start() 启动预热；Web UI 绿点改用 /health
- E13（2026-03-18）：Web UI 迁移 React + TypeScript + Vite + Tailwind + shadcn；Node builder 进 Dockerfile；GET / 返回 SPA
- E14（2026-03-19，**已提交 59a09f5**）：Web UI 产品化对齐（Meshy/Tripo 参考）
  - 生成页：220px 左侧上传面板 + 中央主舞台（空态/处理中粒子动画/完成态 Three.js 查看器）+ 280px 右侧最近生成面板（preview.png 占位图）
  - 图库页：auto-fill 网格（minmax 220px，aspect-ratio 1:1），preview.png + auth fetch + fallback 占位图，pill tabs 筛选
  - 设置页：save/cancel 关闭 Sheet overlay（原 navigate(-1) 错误已修复）
  - 后端：async_engine 启动预热、artifact_store 原子写、task_store pragma 优化

## 关键路径

- `docs/PLAN.md`：架构基线，设计讨论先看这里
- `AGENTS.md`：给执行代码的 AI Coder 的速查说明
- 根目录关键文件：
  - `config.py`
  - `serve.py`
  - `requirements.txt`
  - `requirements-worker.txt`
  - `docker-compose.yml`
  - `deploy.sh`
- 核心目录：
  - `api/`
  - `engine/`
  - `model/`
  - `stages/`
  - `storage/`
  - `observability/`
  - `tests/`
  - `scripts/`
  - `docker/`
  - `docs/`
  - `plan/`

## 阶段状态

- Phase A：完成。Mock 链路、状态流、SSE、取消、webhook、artifacts 已落地
- Phase B：完成。真实 preprocess、真实 Trellis2 provider、artifact backend、Docker/deploy 材料、GPU 服务器 smoke 已落地
- Phase C：完成（2026-03-15）。安全（C1）、可观测性（C4）、可靠性（C2）、多卡并发（C3）、Web 测试页（C5）全部落地
- E9（2026-03-16）：弃用 API_TOKEN task 鉴权，新增 GET /admin/tasks（ADMIN_TOKEN 鉴权）
- E10（2026-03-16）：Token 权限分层（ADMIN_TOKEN → privileged token → user key），彻底移除 API_TOKEN，uvicorn proxy_headers
- E11（2026-03-16）：API 与 Worker 完全解耦，ModelRegistry 懒加载（asyncio.to_thread），FIFO 原子 claim，per-stage Welford ETA，upload-only 输入，/health + /readiness
- Phase D：未开始。多机 worker、阶段解耦未做

## 下一步待办（优先级排序）

### 🔴 近期（E15，下一会话）

**E15-A：后端生成 preview.png 缩略图**
- 目标：generation pipeline 末尾（GLB export 完成后）额外渲染一张 512×512 PNG 存为 artifact `preview.png`
- 现状：前端 task-thumbnail.tsx 已预留 `/v1/tasks/{id}/artifacts/preview.png` 接口，404 时 fallback 占位图。后端不生成，图库和右侧历史面板全是占位图
- 关键约束：不阻塞主任务流程；渲染逻辑放在 stages/ 末尾或独立 post-process stage；artifact 存储走现有 artifact_store 接口
- 验收：图库卡片和生成页右侧历史面板显示真实 3D 截图缩略图

**E15-B：server → gen3d 集成**
- 目标：hey3d server（`/Users/gqk/work/hey3d/server/`）接入 gen3d，iOS 调用 server 的 3D 生成接口，server 持有 platform key 中转 gen3d
- 现状：iOS → server 路径已规划，server 尚未对接 gen3d 任何 API
- 关键约束：server 用 platform key 鉴权；gen3d 接口语义不改；iOS 不直连 gen3d
- 先读 server/CLAUDE.md 了解 server 现有接口结构

### 🟡 中期

**E15-C：Web UI chunk size 优化**
- 现状：主 JS ~939kB，Vite 有 chunk size warning
- 方向：Three.js 和 React Router 做代码分割（dynamic import），vendor chunk 拆分
- 验收：主 chunk < 500kB，Vite warning 消除

**E15-D：release docker-compose.yml 清理**
- 现状：`docker-compose.yml` 含 `build:` 块，生产部署应直接拉镜像
- 方向：做两个文件：`docker-compose.yml`（含 build，开发用）、`docker-compose.release.yml`（纯 image，生产用）

### 🔵 技术债（不紧急）

- IP 白名单校验：E10 已存 IP，校验逻辑等 nginx 路径稳定后开启
- GPU 细粒度进度 hook：`gpu_ss/gpu_shape/gpu_material` 目前是语义占位，未接官方 hook
- Prometheus/Grafana 完整化：目前只有 readiness gauge
- hunyuan3d provider：`model/hunyuan3d/provider.py` 仍是 `NotImplementedError`
- 取消运行中任务：目前只支持 `gpu_queued` 状态

## 已知技术债（长期）

- GPU scheduler：简单 FIFO，`max_batch + deadline` 调度未实现
- GPU worker：进程内 wrapper，不是独立多进程 worker
- Phase D：多机 worker、阶段解耦未开始

## 使用提醒

- 不要再把 `gen3d` 当作刚初始化的新项目
- 设计调整前先读 `docs/PLAN.md` 和相关 `plan/*.md`
- 若任务涉及 scheduler、worker、多机、observability、权限等边界，先确认是在补技术债还是做新阶段能力
