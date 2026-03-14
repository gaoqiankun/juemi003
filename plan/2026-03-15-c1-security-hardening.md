# C1 · 安全收口
Date: 2026-03-15
Status: done
Commits: none

## Goal
堵住公测前必须解决的安全漏洞（SSRF、弱鉴权、资源滥用、内部路径暴露），使服务可以安全暴露给外部用户。

## Key Decisions
- 生产模式（provider != mock）禁用 `file://` 和非 http(s) 协议输入，防 SSRF
- callback URL 强制 http(s)，支持环境变量配置域名白名单
- `API_TOKEN` 取消默认值，未配置时拒绝启动（mock 模式豁免）
- `TaskOptions` 各数值字段加硬上限，改为严格模式（禁止 extra 字段）
- API 层按 token 限流，并发上限和每小时请求数均可配置
- local artifact backend 不返回 `file://` 路径，改为通过 API 代理
- `/metrics` 端点加访问控制

## Changes
| 文件 | 变更说明 |
|------|---------|
| config.py | 新增 ALLOWED_CALLBACK_DOMAINS、RATE_LIMIT_* 配置，取消 API_TOKEN 默认值 |
| api/schemas.py | TaskOptions 数值字段加 le/ge 约束，extra 改严格模式 |
| security.py | 共享 URL 校验、loopback 判断与 token 限流器 |
| api/server.py | mock 模式可无 token 启动、/metrics 加保护、POST /v1/tasks 限流、local artifact 代理下载路由 |
| stages/preprocess/stage.py | 生产模式拒绝 file:// 和非 http(s) URL，并保留 mock 模式本地输入 |
| engine/async_engine.py | image_url / callback_url 提交校验、终态释放并发占用 |
| storage/artifact_store.py | local backend 不返回 file:// 路径，统一改成 /v1/tasks/{id}/artifacts/{filename} |
| tests/test_api.py / tests/test_pipeline.py | 保持 23 条测试，补齐 real mode 4xx、startup fail-fast、限流、metrics、artifact 代理断言 |
| README.md / docs/PLAN.md / docker-compose.yml / deploy.sh | 同步 API_TOKEN、real mode http(s) 输入、artifact 代理和新增安全配置 |

## Notes
- 与 C5 并行（无文件交叉）
- C4 在 C1 之后执行（共享 stages/preprocess/stage.py）
- `pytest tests -q` 结果：`23 passed`
- local artifact URL 已从 `file://` 切到 API 代理；real mode 只能提交 http(s) `image_url`
