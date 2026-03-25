# Session Handoff · 2026-03-25

> 读本文件可快速恢复 2026-03-25 会话的完整上下文。

---

## 今天完成了什么

### Agent 工作流重构
- 建立 `.agent/` 目录（roles/ + plan/ + 工具文档），与 `.claude/`（Claude Code 专有）分离
- 三个角色文件：`backend.md` / `frontend.md` / `debug.md`，各自独立入口
- `pending.md`：API Contract 跨角色交接协议
- `decisions.md`：近期关键行为变更索引
- `friction-log.md`：摩擦记录，每 10 条或 2 周回顾一次
- `impact-map.md` + `troubleshooting.md`：按需查阅，不强制预加载
- 归档 3/10–3/20 历史 plan 到 `plan/archive/`

### 代码质量工具
- ruff（Python）：E/W/F/I/C90，忽略 E501，存量 ~73 条
- ESLint（TypeScript）：typescript-eslint + react-hooks，存量 15 条（`no-explicit-any`）

### 代码质量修复
- Python：F821 × 3（undefined name）+ I001 × 19（import 排序）
- TypeScript：react-hooks × 18（stale closure + hook 用法）+ no-unused-vars × 9

### 大文件重构（全部通过 163 pytest + build 零错误）
| 文件 | 重构前 | 重构后 | 拆出模块 |
|------|--------|--------|---------|
| `storage/artifact_store.py` | 826 | 160 | 6 个子模块 |
| `web/src/app/gen3d-provider.tsx` | 1265 | 212 | 8 个 hook 文件 |
| `storage/task_store.py` | 945 | 85 | 5 个子模块 |
| `web/src/lib/viewer.ts` | 1505 | 14（facade） | 9 个模块 |
| `engine/async_engine.py` | 729 | 400 | eta / events / webhook |

---

## 当前状态

- 测试基线：**163 passed**
- ESLint：**15 条**（全部 `no-explicit-any`，已列为 v0.2）
- 部署中：用户正在验证生产环境

---

## 未完成 / 下一步

| 事项 | 优先级 | 备注 |
|------|--------|------|
| 部署验证结果 | 🔴 立即 | 用户正在进行 |
| `no-explicit-any` × 15 | v0.2 | 纯类型标注，零风险 |
| `async_engine.py` worker/cleanup 拆分 | v0.2 | 时序敏感，需集成测试先覆盖 |
| `api/server.py` 路由拆分（Router 工厂模式） | v0.2 | AppContainer 闭包，中等风险 |
| C901 复杂度超标 × 8 | v0.2 | 需逐函数重构 |
| Docker 技术债（HF_TOKEN / ADMIN_TOKEN） | v0.1 发布前 | 见 CLAUDE.md 技术债表 |
| M4 安装体验 / M5 文档 / M6 QA | v0.1 | 下一个主要工作阶段 |

---

## 这个会话里确认的工作方式

以下是用户明确反馈过的偏好，已同步进全局 `~/.claude/CLAUDE.md`：

1. **一个一个来**：大需求拆小步，每步确认后再往下走，不一次性输出大量改动
2. **分析结果落文档**：AI Coder 的分析不要汇报给用户，直接写进 CLAUDE.md / decisions.md
3. **Prompt 不指定实现**：只给目标和约束，实现细节交给 AI Coder 自己决定
4. **Agent 文件不进代码模块**：roles/plan/decisions 等不放在 `web/`、`api/` 等目录里
5. **并行任务提前说明**：下发并行 Prompt 时告知用户"每个 agent 会创建 planning 文件"
6. **Commit message 用英文**
7. **零风险优先**：有风险的重构（worker loop、api/server.py）推迟，先做零风险的部分

---

## 关键架构决策（本次会话新增）

已同步进 `decisions.md`，这里列摘要：

- `plan/` 移入 `.agent/`，与 `.claude/`（Claude Code 专有）分离
- `viewer3d-runtime.ts` 555 行超过 500 行软警戒，但已拆出所有无状态逻辑，剩余是必要的类体积
- `async_engine.py` worker/cleanup 不拆，时序风险高于收益，列为 v0.2
- `api/server.py` Router 工厂模式方案已设计，v0.2 执行
