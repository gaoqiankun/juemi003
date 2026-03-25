# .claude/ · Agent 工作目录索引

## 我是哪个角色？直接去对应文件

| 角色 | 入口文件 |
|------|---------|
| 后端工程师（改 Python）| `roles/backend.md` |
| 前端工程师（改 web/）| `roles/frontend.md` |
| 调试工程师（查 Bug）| `roles/debug.md` |

## 工具文档（按需查阅）

| 文件 | 用途 |
|------|------|
| `impact-map.md` | 改动 X 会影响哪些模块，必跑哪些测试 |
| `troubleshooting.md` | 遇到报错 → 根因 → 排查位置 |
| `skills/new-provider/SKILL.md` | 接入新 3D 生成模型 |
| `skills/ui-polish/SKILL.md` | UI 打磨检查清单 |

## 目录结构

```
.claude/
├── README.md
├── impact-map.md
├── troubleshooting.md
├── roles/
│   ├── backend.md
│   ├── frontend.md
│   └── debug.md
└── skills/
    ├── new-provider/SKILL.md
    └── ui-polish/SKILL.md
```
