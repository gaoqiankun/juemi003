#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./deploy.sh
#   ./deploy.sh --image cubie3d/cubie3d:20260313-1
#   ./deploy.sh --image cubie3d/cubie3d:20260313-1 --target ubuntu@1.2.3.4 --remote-root /opt/cubie3d
#   ./deploy.sh --image cubie3d/cubie3d:20260313-1 --target ubuntu@1.2.3.4 --remote-root /opt/cubie3d --port 2222
#   ./deploy.sh --image cubie3d/cubie3d:20260313-1 --no-build
#   ./deploy.sh --image cubie3d/cubie3d:20260313-1 --platform linux/amd64
#   ./deploy.sh --trellis2-image cubie3d/trellis2:20260315

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$ROOT_DIR/dist"
TS="$(date +%Y%m%d-%H%M%S)"
RELEASE_NAME="cubie3d-image-$TS"
STAGE_DIR="$DIST_DIR/$RELEASE_NAME"
TARGET=""
REMOTE_ROOT=""
SSH_PORT="22"
DEFAULT_IMAGE="cubie3d/cubie3d:latest"
LATEST_IMAGE="cubie3d/cubie3d:latest"
DEFAULT_TRELLIS2_IMAGE="cubie3d/trellis2:latest"
IMAGE="$DEFAULT_IMAGE"
TRELLIS2_IMAGE="$DEFAULT_TRELLIS2_IMAGE"
DO_BUILD="1"
PLATFORM="linux/amd64"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh
  ./deploy.sh --image cubie3d/cubie3d:20260313-1
  ./deploy.sh --image cubie3d/cubie3d:20260313-1 --target ubuntu@1.2.3.4 --remote-root /opt/cubie3d
  ./deploy.sh --image cubie3d/cubie3d:20260313-1 --target ubuntu@1.2.3.4 --remote-root /opt/cubie3d --port 2222
  ./deploy.sh --image cubie3d/cubie3d:20260313-1 --no-build
  ./deploy.sh --image cubie3d/cubie3d:20260313-1 --platform linux/amd64
  ./deploy.sh --trellis2-image cubie3d/trellis2:20260315

Options:
  --image IMAGE            target app image (default: cubie3d/cubie3d:latest)
                           if IMAGE is not tagged :latest, also tag cubie3d/cubie3d:latest
  --trellis2-image IMAGE   TRELLIS2 base image build arg (default: cubie3d/trellis2:latest)
  --target TARGET          upload release package to remote host
  --remote-root PATH       remote deployment root
  --port PORT              SSH port (default: 22)
  --no-build               skip docker build and use existing IMAGE
  --platform VALUE         docker build platform (default: linux/amd64)
  -h, --help               show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      IMAGE="${2:-}"
      shift 2
      ;;
    --trellis2-image)
      TRELLIS2_IMAGE="${2:-}"
      shift 2
      ;;
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --remote-root)
      REMOTE_ROOT="${2:-}"
      shift 2
      ;;
    --port)
      SSH_PORT="${2:-22}"
      shift 2
      ;;
    --no-build)
      DO_BUILD="0"
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

mkdir -p "$DIST_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

if [[ "$DO_BUILD" == "1" ]]; then
  echo "[INFO] Building image: $IMAGE ($PLATFORM)"
  docker build \
    --platform "$PLATFORM" \
    --build-arg "TRELLIS2_IMAGE=$TRELLIS2_IMAGE" \
    -t "$IMAGE" \
    -f "$ROOT_DIR/docker/Dockerfile" \
    "$ROOT_DIR"

  if [[ "$IMAGE" != *":latest" ]]; then
    echo "[INFO] Tagging latest alias: $LATEST_IMAGE"
    docker tag "$IMAGE" "$LATEST_IMAGE"
  fi
else
  echo "[INFO] Skipping build (--no-build)"
  docker image inspect "$IMAGE" >/dev/null
fi

echo "[INFO] Preparing release files"
cp "$ROOT_DIR/docker-compose.yml" "$STAGE_DIR/"
cp "$ROOT_DIR/README.md" "$STAGE_DIR/"
cp "$ROOT_DIR/.env.example" "$STAGE_DIR/.env.example"

IMAGE_TAR_GZ="$STAGE_DIR/image.tar.gz"

echo "[INFO] Saving image to: $IMAGE_TAR_GZ"
docker save "$IMAGE" | gzip > "$IMAGE_TAR_GZ"

(
  cd "$STAGE_DIR"
  shasum -a 256 image.tar.gz > image.tar.gz.sha256
)

cat > "$STAGE_DIR/DEPLOY_QUICKSTART.txt" <<EOF2
1) docker load -i image.tar.gz
2) mkdir -p ${REMOTE_ROOT:-/opt/cubie3d}/data ${REMOTE_ROOT:-/opt/cubie3d}/models/trellis2
3) ln -sfn ${REMOTE_ROOT:-/opt/cubie3d}/releases/$RELEASE_NAME ${REMOTE_ROOT:-/opt/cubie3d}/current
4) cd ${REMOTE_ROOT:-/opt/cubie3d}/current && cp .env.example .env  # then edit .env and set ADMIN_TOKEN, etc.
5) cd ${REMOTE_ROOT:-/opt/cubie3d}/current && docker compose up -d
EOF2

TAR_PATH="$DIST_DIR/$RELEASE_NAME.tar.gz"
(
  cd "$DIST_DIR"
  if tar --help 2>/dev/null | grep -q -- "--no-mac-metadata"; then
    COPYFILE_DISABLE=1 tar --no-mac-metadata -czf "$TAR_PATH" "$RELEASE_NAME"
  else
    COPYFILE_DISABLE=1 tar -czf "$TAR_PATH" "$RELEASE_NAME"
  fi
)
(
  cd "$DIST_DIR"
  shasum -a 256 "$(basename "$TAR_PATH")" > "$(basename "$TAR_PATH").sha256"
)

echo "[OK] Release package created:"
echo "  $TAR_PATH"
echo "  $TAR_PATH.sha256"

if [[ -n "$TARGET" || -n "$REMOTE_ROOT" ]]; then
  if [[ -z "$TARGET" || -z "$REMOTE_ROOT" ]]; then
    echo "[ERROR] --target and --remote-root must be provided together."
    exit 1
  fi

  REMOTE_RELEASES_DIR="$REMOTE_ROOT/releases"
  REMOTE_RELEASE_DIR="$REMOTE_RELEASES_DIR/$RELEASE_NAME"
  REMOTE_CURRENT_LINK="$REMOTE_ROOT/current"

  echo "[INFO] Uploading release package via rsync..."
  ssh -p "$SSH_PORT" "$TARGET" "mkdir -p '$REMOTE_RELEASES_DIR' '$REMOTE_ROOT/data' '$REMOTE_ROOT/models/trellis2'"
  rsync -avz -e "ssh -p $SSH_PORT" "$TAR_PATH" "$TAR_PATH.sha256" "$TARGET:$REMOTE_RELEASES_DIR/"

  cat <<EOF3

Remote next steps:
  ssh -p $SSH_PORT $TARGET
  cd $REMOTE_RELEASES_DIR
  shasum -a 256 -c $(basename "$TAR_PATH").sha256
  tar -xzf $(basename "$TAR_PATH")
  cd $REMOTE_RELEASE_DIR
  shasum -a 256 -c image.tar.gz.sha256
  docker load -i image.tar.gz
  ln -sfn $REMOTE_RELEASE_DIR $REMOTE_CURRENT_LINK
  cd $REMOTE_CURRENT_LINK
  docker compose up -d
EOF3
fi
