# C5 · Web 测试页
Date: 2026-03-15
Status: planning

## Goal
提供一个轻量 Web 测试页，让内部和公测用户可以直接在浏览器提交 3D 生成任务、查看进度、下载结果，无需命令行工具。

## Key Decisions
- 纯静态单文件（static/index.html），不修改任何现有 Python 文件，与 C1 并行无冲突
- API endpoint 和 token 可在页面内配置并保存到 localStorage
- 进度通过 SSE 实时展示，失败时降级轮询
- GLB 结果用 model-viewer（CDN）内嵌预览 + 下载链接
- 历史 task_id 保存到 localStorage，刷新可恢复
- 静态文件 serve 方式在 C1 完成后单独添加到 api/server.py（一行 mount）

## Changes
| 文件 | 变更说明 |
|------|---------|
| static/index.html | 新建，Web 测试页主体 |

## Notes
- 与 C1 并行，无文件交叉
- C1 完成后补一个 PR：api/server.py 挂载 static/ 目录
- 页面假设从与 API 同源的服务器 serve（避免 CORS 问题）
