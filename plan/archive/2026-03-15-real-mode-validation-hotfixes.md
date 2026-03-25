# real mode 验证热修复
Date: 2026-03-15
Status: done

## Goal
真实环境验证过程中发现并修复的问题。

## Key Decisions
- `/metrics` 鉴权：移除 loopback 免鉴权旁路，配置了 `API_TOKEN` 时必须提供有效 Bearer token；仅“无 token + mock 模式”时放行
- `.env.example` 模板：补 `HF_TOKEN=`，修正 `ALLOWED_CALLBACK_DOMAINS=[]`（空字符串导致 `pydantic_settings` JSON 解析崩溃）
- 去掉 `docker-compose.yml` 的 `user:` 字段和 `.env.example` 里的 `HOST_UID` / `HOST_GID`：强制 uid/gid 映射导致数据目录只读，容器以默认用户运行即可
- artifact 下载不再要求鉴权：URL 中含不可猜测的 task UUID，浏览器预览/下载无需 `Authorization` header

## Changes
| 文件 | 变更说明 |
|------|---------|
| `api/server.py` | 收紧 `/metrics` 鉴权，移除 loopback 免鉴权旁路，并开放 artifact 下载路由的匿名访问 |
| `deploy.sh` | `.env.example` 模板补 `HF_TOKEN=`，修正 `ALLOWED_CALLBACK_DOMAINS=[]`，移除 `HOST_UID` / `HOST_GID` |
| `docker-compose.yml` | 删除 `hey3d-gen3d` service 的 `user:` 字段，容器改为默认用户运行 |
