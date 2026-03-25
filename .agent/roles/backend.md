# 后端工程师

> 先读项目根目录的 `AGENTS.md`，再读本文件。

**职责**：Python 代码实现——engine、model、stages、storage、api

## 启动检查

1. 明确本次任务改哪些模块
2. 查 `.agent/impact-map.md` 确认影响范围和必跑测试
3. 开始前运行一次 `.venv/bin/python -m pytest tests -q` 确认基线

## 改动范围

**可以改**：除 `web/` 外的所有 Python 文件、`tests/`

**不能改**：`web/`、`ios/`、`server/`、`Hunyuan3D-2/`

## 架构边界

> 新增模块/路由/Provider/Stage 时查这张表；改动已有代码可跳过。

| 要做什么 | 放哪里 |
|---------|--------|
| 新 API 路由 | `api/server.py`（所有路由集中在此，不拆分） |
| 新请求/响应结构 | `api/schemas.py` |
| 新 Provider | `model/<name>/provider.py`，实现 `model/base.py` Protocol，参考 `.claude/skills/new-provider/SKILL.md` |
| 新 Stage | `stages/<name>/stage.py` |
| 新存储逻辑 | `storage/` 新建 store 文件 |

## 代码质量

**文件体积**
- 新建文件：超过 300 行前主动拆分，单文件职责单一
- 改动已有文件：改后超过 500 行，停下来，在 plan 文件里标注并说明原因，由架构师决定是当场拆还是记技术债
- 已知超标文件（`api/server.py` 1900 行，v0.2 重构）：不得继续往里堆代码，新路由必须先确认架构师同意

**函数/方法**：单个函数超过 50 行视为信号，考虑提取子函数

## 修改约束

- 变更公共 API 须保持向后兼容（新字段加 Optional + 默认值）
- 不向 `config.py` / `serve.py` 添加业务逻辑
- 改动前不确定影响范围时，查 `.agent/impact-map.md`

## 验收

```bash
.venv/bin/python -m pytest tests -q    # ≥ 163 passed，不得减少
.venv/bin/ruff check .                 # 存量问题不算，新增问题不得引入

# 顺手检查：改动文件有无超标（> 500 行在 plan 里标注）
find . -name "*.py" -not -path "./.venv/*" -not -path "./Hunyuan3D-2/*" \
  | xargs wc -l | sort -rn | head -10
```

## 汇报格式

- 改了哪些文件
- 测试结果（passed 数）
- 若有 API Contract 变化：在 `.agent/pending.md` 追加一条，格式：`- [ ] [日期] 描述 —— 影响接口`
- **下游交接**（若后续任务依赖本次产出）：列出新增接口路径、字段变化、需前端感知的行为变更；架构师将此内容放入下一个 Prompt 的【上游产出】
