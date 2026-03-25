# E4 · API Base URL 默认当前 Origin
Date / Status: 2026-03-15 / done / Commits: none

## Goal
让 Web 测试页的 API Base URL 在未保存配置时默认使用当前页面的 `window.location.origin`。

## Key Decisions
- HTML 输入框默认值不再硬编码，改由页面加载时注入当前 origin
- 若 localStorage 已保存 `baseUrl`，继续优先使用保存值
- 保留用户手动修改并保存的行为

## Changes
| 文件 | 变更说明 |
|------|---------|
| `static/index.html` | `baseUrl` 默认值改为 `window.location.origin`，localStorage 缺省时回退到当前 origin |

## Notes
- 未运行自动化测试；本次仅修改静态页面初始化逻辑
