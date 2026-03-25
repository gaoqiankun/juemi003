# Cubie · AI Coder 执行指南

> 先读本文件，再读架构师在 Prompt 里指定的角色文件（`.agent/roles/`）。

## 项目概况

**Cubie** — 开源 3D 生成服务（图片 → GLB）。FastAPI 后端 + React 前端。

```
gen3d/
├── config.py / serve.py   # 后端入口
├── api/                   # FastAPI 路由与 Schema
├── engine/                # 任务引擎
├── model/                 # Provider 实现（trellis2 / hunyuan3d / step1x3d）
├── stages/                # preprocess / gpu / export
├── storage/               # 5 个 store（SQLite + 文件系统）
├── tests/                 # 基线 163 passed
├── web/                   # React SPA
├── .claude/               # Claude Code 专用：rules/ + skills/
└── .agent/                # Agent 工作目录：roles/ + plan/ + 工具文档
```

## 通用规则

- 不执行任何修改 git 树的操作（`git add/commit/push/rebase`），完成后只汇报结果
- 不修改 `ios/`、`server/`、`Hunyuan3D-2/`
- **开工前**在 `.agent/plan/` 新建 `YYYY-MM-DD-描述.md`（`Status: planning`），列明本次会改哪些文件；完成后改为 `Status: done`
- 若变更影响其他模块的行为，在 `.agent/decisions.md` 顶部追加一条
- 执行中遇到文档缺失、路径错误、流程不清晰等阻碍，在 `.agent/friction-log.md` 随手记一行
- 不升级依赖，除非明确要求

## 验收命令

```bash
.venv/bin/python -m pytest tests -q    # 改了 Python：≥ 163 passed
cd web && npm run build            # 改了前端：零错误
```
