# MINIO_DIR 配置清理
Date / Status: 2026-03-21 / done / Commits: n/a

## Goal
移除 `MINIO_DIR` 相关配置项，因为 `ARTIFACT_STORE_MODE=local` 时不会使用 MinIO 数据目录挂载。

## Key Decisions
- 不改 `ARTIFACT_STORE_MODE` 和任何 local artifact 存储逻辑
- `config.py` 若已无 `MINIO_DIR` 配置项，则不额外改动
- 仅清理 `.env.example` 和 `docker-compose.yml` 中暴露给部署层的 `MINIO_DIR` 残留

## Changes
- 删除 `.env.example` 中的 `MINIO_DIR` 示例配置
- 删除 `docker-compose.yml` 里 `minio` 服务对 `MINIO_DIR` 的 bind mount
- 保持 `deploy.sh` 不变，因为当前已无 `MINIO_DIR` 引用

## Notes
- 已验证 `grep -r "MINIO_DIR"` 在指定文件类型范围内为空
- 已验证 `python -m pytest tests -q` 通过
