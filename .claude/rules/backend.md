# Backend Rules

> 当修改 Python 文件（`web/` 目录之外）时适用。

## 命令

```bash
.venv/bin/python -m pytest tests -q                      # 基线 163 passed，不得减少
python -m pytest tests/test_xxx.py -q         # 只跑单个文件
```

## 架构边界（新代码放哪里）

| 要做什么 | 放哪里 |
|---------|--------|
| 新 API 路由 | `api/server.py`（不拆分，当前设计如此） |
| 新请求/响应数据结构 | `api/schemas.py` |
| 新 3D 生成 Provider | `model/<name>/provider.py`，实现 `model/base.py` 的 Protocol |
| 新 Stage | `stages/<name>/stage.py`，继承 `stages/base.py` |
| 新存储逻辑 | `storage/` 目录，新建独立 store 文件 |
| 启动/配置 | `config.py` 加字段，`serve.py` 调整启动逻辑 |

## 修改约束

- 不升级依赖版本，除非明确要求
- 不修改 `Hunyuan3D-2/`（外部 repo，untracked）
- 变更公共 API（路径/参数/响应结构）前确认不破坏现有调用方
- 新增 Schema 字段优先加 Optional + 默认值，保持向后兼容
- 不向 `config.py` 或 `serve.py` 添加业务逻辑

## 测试要求

- Bug 修复：复现 → 修复 → 加回归测试 → 全量测试通过
- 新功能：加单测覆盖正常路径 + 主要错误路径
- 修改 engine 核心（async_engine / pipeline / scheduler）：必须跑全量测试

## 验收标准

- `.venv/bin/python -m pytest tests -q` 通过且 passed 数 ≥ 163
- 没有改变现有 API 的 breaking change
