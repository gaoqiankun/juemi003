# Hey3D gen3d · Claude 架构师记忆

> 子仓库：`/Users/gqk/work/hey3d/gen3d/`（独立 git 仓库）
> 最后更新：2026-03-19

## 规划日志

- 历史规划和执行记录在 `plan/`
- `plan/2026-03-19-web-ui-product-reference-alignment.md`：状态 done / uncommitted，本次会话主要 plan

## 当前状态（2026-03-19）

- `gen3d` 已是可运行的 Python/FastAPI 3D 生成服务，Phase A/B/C 全部完成
- 当前测试基线：`python -m pytest tests -q` 为 `71 passed`
- Provider：
  - `mock`：`MockTrellis2Provider`
  - `real`：`Trellis2Provider`
  - `hunyuan3d`：占位，未实现
- Artifact backend：
  - `local`
  - `minio`
- 对外功能已具备：任务提交、任务查询、SSE 事件流、取消、终态 webhook、artifacts 查询
- 部署材料已齐：`docker/Dockerfile`、根目录 `docker-compose.yml`、`deploy.sh`
- D1 已完成：`docker/trellis2/` 已拆成独立基础镜像目录，TRELLIS.2 CUDA 扩展编译从应用镜像剥离，常规应用镜像 build 目标 < 2 分钟
- 真实 TRELLIS2 链路已在 GPU 服务器跑通
- **Phase C 新增能力（已上线）**：
  - C1：安全收口（SSRF 防护、scoped token 分层、rate limit、artifact 代理、/metrics 访问控制）
  - C2：基础可靠性（服务重启任务恢复、webhook 指数退避重试、幂等 key 竞态修复、任务超时）
  - C3：多卡并发（GPU_DEVICE_IDS 多进程 worker、QUEUE_MAX_SIZE 有界队列、503 拒绝）
  - C4：可观测性（structlog JSON 结构化日志、Prometheus 指标）
  - C5：Web UI（多页面 SPA：生成页/图库/设置，Three.js 预览，Hash Router，深色商业化风格）
- E12（2026-03-18）：启动预热 + /health UI 对齐。engine.start() 后自动后台预热默认模型；Web UI 连接状态改为基于 /health，任务提交不再依赖 /ready
- E13（2026-03-18）：Web UI 迁移到 React + TypeScript + Vite + Tailwind + shadcn 风格组件。源码在 web/，Dockerfile 增加 Node builder stage，dist 在镜像构建时生成。GET / 返回 SPA index.html，支持 /gallery、/settings 客户端路由。旧 static/ 目录已删除
- E14（2026-03-19，进行中，未提交）：Web UI 产品化对齐。参考 Meshy/Tripo 重构布局：生成页改为左侧 220px 上传面板 + 中央主舞台 + 右侧最近生成列表，粒子动画生成中态，Three.js 完成态全屏查看器。图库改为 auto-fill 卡片网格（minmax 220px），缩略图预留 preview.png 接口（fallback 占位图）。**部署前待完成项**：① 图库 auto-fill 网格 ② 图库缩略图改用 preview.png + fallback ③ 设置页保存/取消后 navigate(-1) ④ 生成页空态中央内容 ⑤ 生成页底部工具栏空态时隐藏

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

## 已知待办 / 技术债

- `model/hunyuan3d/provider.py` 仍是 `NotImplementedError` 占位
- GPU scheduler 目前只是简单 FIFO 队列，`max_batch + deadline` 调度未实现
- GPU worker 当前是进程内 wrapper，不是独立多进程 worker
- Real mode 的 `gpu_ss` / `gpu_shape` / `gpu_material` 进度仍是语义占位，未接上官方细粒度 hook
- 取消只支持 `gpu_queued` 状态，运行中阶段不可中断
- `observability/metrics.py` 目前只有 readiness gauge，Prometheus/Grafana 未完成
- 下一步待办：
  ① **E14 收尾并部署**（本次会话未完成，见 E14 待完成项）
  ② 后端生成 preview.png 缩略图（generation pipeline 末尾多存一张，图库卡片直接用）
  ③ server → gen3d 集成（iOS 路径，已确认为中转架构：iOS → server → gen3d）
  ④ release 包 `docker-compose.yml` 去掉 `build:` 块
  ⑤ IP 白名单校验逻辑（E10 只存不校验，等 nginx 路径稳定后开启）
  ⑥ GPU 细粒度进度 hook（gpu_ss/gpu_shape/gpu_material 目前是占位）
  ⑦ Prometheus/Grafana 完整化（目前只有 readiness gauge）
  ⑧ Web UI chunk size 优化（当前主 JS ~939kB，Vite 有 warning）

## 使用提醒

- 不要再把 `gen3d` 当作刚初始化的新项目
- 设计调整前先读 `docs/PLAN.md` 和相关 `plan/*.md`
- 若任务涉及 scheduler、worker、多机、observability、权限等边界，先确认是在补技术债还是做新阶段能力
