# gen3d 模型下载脚本与本地产物清理
Date / Status: 2026-03-15 / done

## Goal

整理本地未提交的部署辅助改动：让模型下载脚本兼容更多 Hugging Face 下载入口，并避免根目录真实 smoke 产物继续污染工作树。

## Key Decisions

- `scripts/download_models.sh` 优先尝试 `hf` CLI，其次回退到 `huggingface-cli`，最后使用 `huggingface_hub.snapshot_download()`
- 根目录 `model.glb` 视为本地真实 smoke 产物，不纳入版本库
- 通过 `.gitignore` 忽略 `/model.glb`，而不是把生成产物提交进 git

## Changes

- 更新 `scripts/download_models.sh`
  - 新增 Python 解释器探测
  - 支持 `hf download`
  - 保留 `huggingface-cli download` 回退
  - 当 CLI 不可用时，回退到 `huggingface_hub.snapshot_download()`
- 更新 `.gitignore`
  - 忽略根目录 `/model.glb`

## Notes

- `model.glb` 当前是本地 2026-03-14 真实链路 smoke 产物，不是仓库源码资产
