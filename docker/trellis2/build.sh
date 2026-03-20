#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./docker/trellis2/build.sh
#   ./docker/trellis2/build.sh --image cubify3d/trellis2:20260315
#   ./docker/trellis2/build.sh --image cubify3d/trellis2:20260315 --platform linux/amd64
#   ./docker/trellis2/build.sh --image cubify3d/trellis2:20260315 --push
#
# Optional environment build args:
#   FLASHATTN_DEVEL_IMAGE
#   FLASHATTN_RUNTIME_IMAGE
#   TRELLIS2_REPO_URL
#   TRELLIS2_REF
#   TORCH_CUDA_ARCH_LIST

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DEFAULT_IMAGE="cubify3d/trellis2:latest"
LATEST_IMAGE="cubify3d/trellis2:latest"
IMAGE="$DEFAULT_IMAGE"
DO_PUSH="0"
PLATFORM="linux/amd64"

usage() {
  cat <<'EOF'
Usage:
  ./docker/trellis2/build.sh
  ./docker/trellis2/build.sh --image cubify3d/trellis2:20260315
  ./docker/trellis2/build.sh --image cubify3d/trellis2:20260315 --platform linux/amd64
  ./docker/trellis2/build.sh --image cubify3d/trellis2:20260315 --push

Options:
  --image IMAGE       target image name (default: cubify3d/trellis2:latest)
                      if IMAGE is not tagged :latest, also tag cubify3d/trellis2:latest
                      and push that latest tag too when --push is set
  --platform VALUE    docker build platform (default: linux/amd64)
  --push              push IMAGE; if auto-tagged, also push cubify3d/trellis2:latest
  -h, --help          show this help

Optional environment build args:
  FLASHATTN_DEVEL_IMAGE
  FLASHATTN_RUNTIME_IMAGE
  TRELLIS2_REPO_URL
  TRELLIS2_REF
  TORCH_CUDA_ARCH_LIST
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      IMAGE="${2:-}"
      shift 2
      ;;
    --push)
      DO_PUSH="1"
      shift
      ;;
    --platform)
      PLATFORM="${2:-linux/amd64}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1"
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is not installed"
  exit 1
fi

build_args=(
  FLASHATTN_DEVEL_IMAGE
  FLASHATTN_RUNTIME_IMAGE
  TRELLIS2_REPO_URL
  TRELLIS2_REF
  TORCH_CUDA_ARCH_LIST
)

docker_build_cmd=(
  docker build
  --platform "$PLATFORM"
  -t "$IMAGE"
  -f "$ROOT_DIR/docker/trellis2/Dockerfile"
)

for arg_name in "${build_args[@]}"; do
  arg_value="${!arg_name:-}"
  if [[ -n "$arg_value" ]]; then
    docker_build_cmd+=(--build-arg "${arg_name}=${arg_value}")
  fi
done

docker_build_cmd+=("$ROOT_DIR/docker/trellis2")

echo "[INFO] Building image: $IMAGE ($PLATFORM)"
"${docker_build_cmd[@]}"

if [[ "$IMAGE" != *":latest" ]]; then
  echo "[INFO] Tagging latest alias: $LATEST_IMAGE"
  docker tag "$IMAGE" "$LATEST_IMAGE"
fi

if [[ "$DO_PUSH" == "1" ]]; then
  echo "[INFO] Pushing image: $IMAGE"
  docker push "$IMAGE"

  if [[ "$IMAGE" != *":latest" ]]; then
    echo "[INFO] Pushing latest alias: $LATEST_IMAGE"
    docker push "$LATEST_IMAGE"
  fi
fi
