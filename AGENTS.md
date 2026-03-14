# gen3d AI Coder 执行指南

> 本文档给执行代码的 AI Coder 使用。开始任何开发前，先读 `docs/PLAN.md`、本文件和相关 `plan/*.md`。

## 1. 工作方式

- 设计以 `docs/PLAN.md` 为基准，不要自行发明架构
- 根目录 `hey3d/` 不是 git 仓库，只在 `gen3d/` 内提交
- 不要修改 `ios/` 和 `server/` 的文件
- 完成任务后更新对应 `plan/` 文件，或新建 plan 文件，并与代码一起提交

## 2. 当前仓库状态

- `gen3d` 已落地，不是从零开始的空仓库
- 当前阶段：
  - Phase A：完成
  - Phase B：完成
  - Phase C：待启动
  - Phase D：未开始
- 当前能力：
  - Python/FastAPI 3D 生成服务
  - provider：`mock` / `real`
  - artifact backend：`local` / `minio`
  - API：任务提交、查询、SSE、取消、webhook、artifacts
  - Docker + `deploy.sh` 部署材料齐全，真实链路已在 GPU 服务器跑通
- 当前测试基线：`python -m pytest tests -q` 为 `23 passed`
- `Hunyuan3DProvider` 仍未实现

## 3. 实际目录结构

```text
gen3d/
├── config.py
├── serve.py
├── requirements.txt
├── requirements-worker.txt
├── docker-compose.yml
├── deploy.sh
├── api/
├── engine/
├── model/
├── stages/
├── storage/
├── observability/
├── tests/
├── scripts/
├── docker/
├── docs/
└── plan/
```

补充说明：
- `docker/Dockerfile` 是当前主部署镜像
- `docker/flashattn/` 存放 flash-attn 基础镜像构建材料
- `docs/PLAN.md` 是架构基线，`docs/PLAN.bak.md` 是备份

## 4. 当前实现边界

不要把下面这些能力误写成“已经完成”：

- `model/hunyuan3d/provider.py`：`NotImplementedError` 占位
- `stages/gpu/scheduler.py`：只有简单 FIFO 队列，`max_batch + deadline` 调度未实现
- `stages/gpu/worker.py`：当前是进程内 wrapper，不是独立多进程 worker
- `model/trellis2/provider.py`：real mode 的 `gpu_ss` / `gpu_shape` / `gpu_material` 进度仍是语义占位
- 取消只支持 `gpu_queued` 状态，运行中阶段不可中断
- `observability/metrics.py`：只有 readiness gauge
- artifact 写宿主机 bind mount 的权限收口还没做

## 5. 本地开发与测试

仓库通过 `.python-version` 固定到 `hey3d_gen3d`：

```bash
cd /Users/gqk/work/hey3d/gen3d
pyenv local hey3d_gen3d
python -m pip install -r requirements.txt
python serve.py
python serve.py --check-real-env
python -m pytest tests -q
```

说明：
- `.python-version` 当前内容是 `hey3d_gen3d`
- real mode 还需要 `requirements-worker.txt` 里说明的 GPU/TRELLIS2 依赖、模型目录，以及可选的对象存储配置
- smoke helper 在 `scripts/bench.py`

## 6. 修改时注意

- 保持现有 API、状态流、artifact 语义兼容
- 若任务涉及 scheduler、worker、多机、observability、权限等边界，先查相关 plan 文件
- 不要再使用早期规划期的过时描述
- 文档、代码、plan 要同步，不要只改其中一处

## 7. 参考

- `docs/PLAN.md`
- `plan/`
- `CLAUDE.md`
- `/Users/gqk/work/hey3d/AGENTS.md`
