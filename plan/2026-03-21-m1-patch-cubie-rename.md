# M1 Patch · 品牌重命名 Cubify → Cubie
Date: 2026-03-21
Status: done

## Goal
将开源项目品牌从 "Cubify 3D" 改为 "Cubie 3D"，"Cubify" 保留为商业品牌不出现在本项目中。

## Key Decisions

- 显示名：`Cubify 3D` → `Cubie 3D`，`Cubify` → `Cubie`
- 代码标识符：`cubify3d` → `cubie3d`
- 环境变量：去掉品牌前缀，直接用功能性名称（`CUBIE_DATA_DIR` → `DATA_DIR`）
- Docker 项目/服务/容器/镜像：`cubify3d` → `cubie3d`（外部可见，保留品牌）
- SQLite 文件名：`cubify3d.sqlite3` → `app.sqlite3`（不耦合项目名）
- MinIO bucket：`cubify3d-artifacts` → `artifacts`
- Prometheus metrics 前缀：`cubify3d_` → 去掉前缀
- localStorage key：`cubify3d-` → `app-`

## Changes

- 品牌显示名统一替换为 `Cubie 3D` / `Cubie`
- 代码标识符统一替换为 `cubie3d`，并同步更新 Web package name、service name、worker thread name、示例域名与文案
- 环境变量去品牌前缀：`CUBIFY_IMAGE` / `CUBIFY_DATA_DIR` / `CUBIFY_MODEL_DIR` / `CUBIFY_MINIO_DIR` / `CUBIFY_DEV_API_TARGET`
  分别改为 `IMAGE` / `DATA_DIR` / `MODEL_DIR` / `MINIO_DIR` / `DEV_API_TARGET`
- SQLite 默认文件名改为 `app.sqlite3`，测试中的 real-mode 临时库名同步改为 `app-real.sqlite3`
- MinIO bucket 名统一改为 `artifacts`
- Prometheus metrics 前缀 `cubify3d_` 全部移除，测试断言与文档同步更新
- Web 持久化 key 去品牌化：
  - `cubify3d-*` → `app-*`
  - `cubify3d.react.*` → `app.react.*`
  - `cubify3d:model-etag:` → `app:model-etag:`
- Docker 外部可见名称统一改为 `cubie3d`
- 实际变更文件：
  - `.env.example`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `LICENSE`
  - `README.md`
  - `config.py`
  - `deploy.sh`
  - `docker-compose.yml`
  - `docker/Dockerfile`
  - `docker/flashattn/Dockerfile.runtime`
  - `docker/flashattn/build.sh`
  - `docker/flashattn/docker-compose.yaml`
  - `docker/trellis2/Dockerfile`
  - `docker/trellis2/build.sh`
  - `docs/PLAN.md`
  - `engine/async_engine.py`
  - `observability/metrics.py`
  - `scripts/bench.py`
  - `serve.py`
  - `tests/test_api.py`
  - `tests/test_pipeline.py`
  - `web/index.html`
  - `web/package-lock.json`
  - `web/package.json`
  - `web/src/app/gen3d-provider.tsx`
  - `web/src/components/app-shell.tsx`
  - `web/src/components/layout/admin-shell.tsx`
  - `web/src/components/layout/user-shell.tsx`
  - `web/src/data/admin-mocks.ts`
  - `web/src/hooks/use-locale.ts`
  - `web/src/hooks/use-theme.tsx`
  - `web/src/i18n/en.json`
  - `web/src/i18n/zh-CN.json`
  - `web/src/lib/user-config.ts`
  - `web/src/lib/viewer.ts`
  - `web/src/pages/proof-shots-page.tsx`
  - `web/src/pages/reference-compare-page.tsx`
  - `web/vite.config.ts`
  - `web/node_modules/.package-lock.json`

## Notes

- 纯文本替换为主，不改逻辑
- 测试文件中的断言（bucket name、metrics prefix）也要同步更新
- 已验证：`npm run build` 通过，`python -m pytest tests -q` 通过（在仓库 `.venv` 中执行）
- design/ 和 plan/ 历史文件无需修改
