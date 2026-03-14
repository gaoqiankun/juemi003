#!/usr/bin/env bash

set -euo pipefail

MODEL_REPO_ID="${MODEL_REPO_ID:-microsoft/TRELLIS.2-4B}"
MODEL_DIR="${MODEL_DIR:-/models/trellis2}"
MODEL_REVISION="${MODEL_REVISION:-main}"

mkdir -p "${MODEL_DIR}"

pick_python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
  else
    printf '%s\n' ""
  fi
}

PYTHON_CMD="$(pick_python_cmd)"

if command -v hf >/dev/null 2>&1; then
  DOWNLOAD_CMD=(
    hf download
    "${MODEL_REPO_ID}"
    --local-dir "${MODEL_DIR}"
  )
  if [[ -n "${MODEL_REVISION}" ]]; then
    DOWNLOAD_CMD+=(--revision "${MODEL_REVISION}")
  fi
  echo "Downloading ${MODEL_REPO_ID} into ${MODEL_DIR} with hf"
  "${DOWNLOAD_CMD[@]}"
elif command -v huggingface-cli >/dev/null 2>&1; then
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
elif [[ -n "${PYTHON_CMD}" ]] && "${PYTHON_CMD}" -c "import huggingface_hub" >/dev/null 2>&1; then
  echo "Downloading ${MODEL_REPO_ID} into ${MODEL_DIR} with huggingface_hub.snapshot_download()"
  MODEL_REPO_ID="${MODEL_REPO_ID}" \
  MODEL_DIR="${MODEL_DIR}" \
  MODEL_REVISION="${MODEL_REVISION}" \
  "${PYTHON_CMD}" - <<'PY'
import os

from huggingface_hub import snapshot_download

repo_id = os.environ["MODEL_REPO_ID"]
local_dir = os.environ["MODEL_DIR"]
revision = os.environ.get("MODEL_REVISION") or None
token = os.environ.get("HF_TOKEN")

snapshot_download(
    repo_id=repo_id,
    local_dir=local_dir,
    revision=revision,
    token=token,
)
PY
else
  echo "Missing Hugging Face download tooling. Install 'huggingface_hub' or the 'hf' CLI first." >&2
  exit 1
fi

echo "Model snapshot is ready at ${MODEL_DIR}"
