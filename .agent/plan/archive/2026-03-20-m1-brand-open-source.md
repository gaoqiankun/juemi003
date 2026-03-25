# M1 · 品牌重命名 & 开源化基础

Date: 2026-03-20
Status: done

## Goal

将项目从内部代号 gen3d 转型为公开开源项目 Cubify 3D：
统一所有品牌标识、清理内部耦合、补充开源必要文件。

## Key Decisions

- 本地目录名 `gen3d/` 暂不变（git repo 重命名由用户手动操作）
- API 路径（`/api/v1/...`）不变，避免破坏现有集成
- License 选 Apache 2.0
- 环境变量前缀、Docker 镜像名、日志前缀、Web UI 显示名统一改为 cubify 相关

## Changes

- 品牌标识统一为 `cubify3d` / `Cubify 3D`：更新 Web UI 标题与 header、FastAPI `service_name`、Prometheus 指标名、对象存储 bucket、默认 sqlite 文件名、Docker Compose project/service/container/image 名称
- 环境变量前缀从 `GEN3D_*` / `HEY3D_*` 统一改为 `CUBIFY_*`：`CUBIFY_IMAGE`、`CUBIFY_DATA_DIR`、`CUBIFY_MODEL_DIR`、`CUBIFY_MINIO_DIR`、`CUBIFY_DEV_API_TARGET`
- 清理内部耦合：移除仓库内 `hey3d` 引用，替换测试中的内部 FRP 域名为 `https://cubify3d.example.com`，将 `.python-version` 从私有虚拟环境别名改为通用 `3.12.7`
- 添加开源基础文件：新增 Apache 2.0 `LICENSE`，重写 `README.md` 为开源首页格式
- 更新开发文档：同步 `AGENTS.md`、`CLAUDE.md`、`docs/PLAN.md`
- 同步测试与构建验证：测试断言、metrics 名称、MinIO bucket 断言均切到新品牌

## Notes

- M1 是其他模块的前置依赖，完成后再启动 M2/M3
- 改完后测试必须全部通过（85 passed 基线）
- 验证结果：`PYENV_VERSION=hey3d_gen3d python -m pytest tests -q` 为 `85 passed`
- `npm run build` 已通过；`web/dist/index.html` 标题为 `Cubify 3D`
- `docker compose config` 可正确解析新 project/service/env 前缀；`docker compose up` 在当前机器因 Docker daemon 不可用而未能完成健康检查
