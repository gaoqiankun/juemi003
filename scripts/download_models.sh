#!/usr/bin/env bash

set -euo pipefail

MODEL_REPO_ID="${MODEL_REPO_ID:-microsoft/TRELLIS.2-4B}"
MODEL_DIR="${MODEL_DIR:-/models/trellis2}"
MODEL_REVISION="${MODEL_REVISION:-main}"

mkdir -p "${MODEL_DIR}"

if command -v huggingface-cli >/dev/null 2>&1; then
  DOWNLOAD_CMD=(
    huggingface-cli download
    "${MODEL_REPO_ID}"
    --local-dir "${MODEL_DIR}"
    --local-dir-use-symlinks False
    --resume-download
  )
  if [[ -n "${MODEL_REVISION}" ]]; then
    DOWNLOAD_CMD+=(--revision "${MODEL_REVISION}")
  fi
  echo "Downloading ${MODEL_REPO_ID} into ${MODEL_DIR} with huggingface-cli"
  "${DOWNLOAD_CMD[@]}"
elif python -m huggingface_hub --help >/dev/null 2>&1; then
  DOWNLOAD_CMD=(
    python -m huggingface_hub download
    "${MODEL_REPO_ID}"
    --local-dir "${MODEL_DIR}"
    --local-dir-use-symlinks False
    --resume-download
  )
  if [[ -n "${MODEL_REVISION}" ]]; then
    DOWNLOAD_CMD+=(--revision "${MODEL_REVISION}")
  fi
  echo "Downloading ${MODEL_REPO_ID} into ${MODEL_DIR} with python -m huggingface_hub"
  "${DOWNLOAD_CMD[@]}"
else
  echo "Missing huggingface download tooling. Install 'huggingface_hub' first." >&2
  exit 1
fi

echo "Model snapshot is ready at ${MODEL_DIR}"
