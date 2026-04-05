# Migrate to pyproject.toml + uv lockfile
Date: 2026-04-05
Status: approved

## Goal

将 `requirements.txt` / `requirements-worker.txt` 迁移为 `pyproject.toml`，生成 `uv.lock`，更新 Docker 构建使用 `uv sync`。

## 设计决策

- `requirements.txt` → `[project.dependencies]`（runtime）
- `requirements-worker.txt` 中额外的包 → `[dependency-groups] worker`（GPU 机专用）
- dev 工具（`pytest`、`ruff`）从 runtime deps 移入 `[dependency-groups] dev`
- Docker 安装 uv，用 `uv sync --group worker --frozen` 替换 `pip install -r requirements-worker.txt`
- `docker/trellis2/Dockerfile` 和 `docker/flashattn/Dockerfile` 不动（全是 GPU source builds，无 requirements 文件）
- `requirements.txt` 和 `requirements-worker.txt` 删除（pyproject.toml 为唯一来源）
- `ruff` 配置若存在于独立文件，合并进 `pyproject.toml [tool.ruff]`；`pytest` 同理
- Python 版本在 `pyproject.toml` 的 `requires-python` 中声明（对齐 `.python-version` 的 3.12.7）

## 文件变更

- 新增 `pyproject.toml`
- 新增 `uv.lock`（`uv lock` 生成）
- 更新 `docker/Dockerfile`：安装 uv，用 `uv sync` 替换 pip install
- 删除 `requirements.txt`、`requirements-worker.txt`
- 若有独立 `ruff.toml` 或 `pytest.ini`：合并后删除

## Acceptance Criteria

- [ ] `uv sync --group dev` 可在开发机正常运行（安装所有 dev + runtime 依赖）
- [ ] `uv run python -m pytest tests -q` 通过（≥ 163 passed）
- [ ] `uv run ruff check .` 无新增 issue
- [ ] `docker/Dockerfile` 构建逻辑正确（Worker 可在 CI 或部署机验证；如无法验证，注释说明）
- [ ] `requirements.txt` 和 `requirements-worker.txt` 已删除
- [ ] `uv.lock` 已提交

## Out of scope

- `docker/trellis2/Dockerfile`、`docker/flashattn/Dockerfile` 不改
- CI pipeline 改动（如有，单独处理）
