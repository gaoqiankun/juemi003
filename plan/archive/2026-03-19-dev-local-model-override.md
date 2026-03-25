# Dev Proxy 本地模型覆盖
Date / Status: 2026-03-19 / done / Commits: uncommitted

## Goal
在本地 `DEV_PROXY_TARGET` 联调模式下，把 `.../artifacts/model.glb` 改为直接返回工作区内提供的本地 GLB 文件，避免继续受线上 artifact 下载速度影响，从而单独验证生成页和图库查看器的后续渲染链路。

## Key Decisions
- 只覆盖 `model.glb` 下载请求，其他 `/v1/...` 接口仍然按原逻辑代理到线上部署
- 覆盖逻辑仅在配置 `DEV_PROXY_TARGET` 且显式提供 `DEV_LOCAL_MODEL_PATH` 时生效，不影响默认开发和生产路径
- 本地模型覆盖发生在 dev proxy 分流前，确保请求不会先被透明代理到线上

## Changes
- `config.py` 新增 `DEV_LOCAL_MODEL_PATH` 配置项
- `api/server.py` 新增开发态本地模型解析逻辑；匹配 `.../artifacts/model.glb` 时直接返回本地文件，并让该请求跳过 dev proxy
- `tests/test_api.py` 增加回归，验证 dev proxy 开启时 `model.glb` 由本地文件返回，而 `/ready` 等其他请求继续代理到线上

## Notes
- 全量回归结果：`python -m pytest tests -q` -> `74 passed`
- 当前用于联调的本地模型文件路径是 `gen3d/model.glb`
