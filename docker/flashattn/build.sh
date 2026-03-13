#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

target_repository="${TARGET_REPOSITORY:-hey3d/flashattn}"
force_rebuild=0
compose_build_args=()
base_image="${BASE_IMAGE:-pytorch/pytorch:2.6.0-cuda12.4-cudnn9-devel}"

pick_pip_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3 -m pip"
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' "python -m pip"
  elif command -v pip >/dev/null 2>&1; then
    printf '%s\n' "pip"
  else
    printf '%s\n' ""
  fi
}

host_pip_cmd="$(pick_pip_cmd)"

pick_python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
  else
    printf '%s\n' ""
  fi
}

host_python_cmd="$(pick_python_cmd)"

pip_config_get() {
  local key="$1"

  if [[ -z "$host_pip_cmd" ]]; then
    return 1
  fi

  local value=""
  if ! value="$($host_pip_cmd config get "$key" 2>/dev/null)"; then
    return 1
  fi

  value="$(printf '%s' "$value" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g; s/^ //; s/ $//')"
  [[ -n "$value" ]] || return 1
  printf '%s\n' "$value"
}

resolve_pip_build_env() {
  if [[ -z "${PIP_INDEX_URL:-}" ]]; then
    PIP_INDEX_URL="$(pip_config_get global.index-url || true)"
    export PIP_INDEX_URL
  fi

  if [[ -z "${PIP_EXTRA_INDEX_URL:-}" ]]; then
    PIP_EXTRA_INDEX_URL="$(pip_config_get global.extra-index-url || true)"
    export PIP_EXTRA_INDEX_URL
  fi

  if [[ -z "${PIP_TRUSTED_HOST:-}" ]]; then
    PIP_TRUSTED_HOST="$(pip_config_get global.trusted-host || true)"
    export PIP_TRUSTED_HOST
  fi

  if [[ -z "${PIP_DEFAULT_TIMEOUT:-}" ]]; then
    PIP_DEFAULT_TIMEOUT="$(pip_config_get global.timeout || true)"
    export PIP_DEFAULT_TIMEOUT
  fi
}

github_api_headers() {
  printf '%s\n' "Accept: application/vnd.github+json"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    printf '%s\n' "Authorization: Bearer ${GITHUB_TOKEN}"
  fi
}

fetch_release_json() {
  local version="${1:-}"
  local url=""

  if [[ -n "$version" && "$version" != "latest" ]]; then
    if [[ "$version" == v* ]]; then
      url="https://api.github.com/repos/Dao-AILab/flash-attention/releases/tags/${version}"
    else
      url="https://api.github.com/repos/Dao-AILab/flash-attention/releases/tags/v${version}"
    fi
  else
    url="https://api.github.com/repos/Dao-AILab/flash-attention/releases/latest"
  fi

  local curl_args=(-fsSL)
  while IFS= read -r header; do
    curl_args+=(-H "$header")
  done < <(github_api_headers)

  curl "${curl_args[@]}" "$url"
}

inspect_base_image_for_flash_attn_wheel() {
  docker run --rm --entrypoint python "$base_image" -c '
import json
import platform
import sys
import torch

def torch_minor(version: str) -> str:
    base = version.split("+", 1)[0]
    parts = base.split(".")
    return ".".join(parts[:2])

def cuda_major(version: str | None) -> str:
    if not version:
        return "unknown"
    return version.split(".", 1)[0]

payload = {
    "torch": torch_minor(torch.__version__),
    "cuda": cuda_major(torch.version.cuda),
    "cxx11abi": "TRUE" if torch.compiled_with_cxx11_abi() else "FALSE",
    "python_tag": f"cp{sys.version_info.major}{sys.version_info.minor}",
    "platform_tag": "linux_x86_64" if platform.machine() == "x86_64" else f"linux_{platform.machine()}",
}
print(json.dumps(payload))
'
}

resolve_flash_attn_install_target() {
  if [[ -n "${FLASH_ATTN_INSTALL_TARGET:-}" && "${FLASH_ATTN_INSTALL_TARGET}" != "flash-attn" ]]; then
    return 0
  fi

  if [[ -z "$host_python_cmd" ]]; then
    printf 'failed to resolve flash-attn install target: no host python found\n' >&2
    exit 2
  fi

  local wheel_context release_json
  if ! wheel_context="$(inspect_base_image_for_flash_attn_wheel)"; then
    printf 'failed to resolve flash-attn install target: failed to inspect base image %s\n' "$base_image" >&2
    exit 2
  fi

  local release_selector="${FLASH_ATTN_VERSION:-2.8.3}"
  if ! release_json="$(fetch_release_json "$release_selector")"; then
    printf 'failed to resolve flash-attn install target: failed to fetch release metadata for %s\n' "$release_selector" >&2
    exit 2
  fi

  local resolved
  if ! resolved="$("$host_python_cmd" - "$wheel_context" "$release_json" <<'PY'
import json
import sys

context = json.loads(sys.argv[1])
release = json.loads(sys.argv[2])

release_tag = release["tag_name"]
release_version = release_tag[1:] if release_tag.startswith("v") else release_tag

if context["cuda"] == "unknown":
    raise SystemExit(2)

candidate_name = (
    f"flash_attn-{release_version}"
    f"+cu{context['cuda']}"
    f"torch{context['torch']}"
    f"cxx11abi{context['cxx11abi']}"
    f"-{context['python_tag']}"
    f"-{context['python_tag']}"
    f"-{context['platform_tag']}.whl"
)

for asset in release.get("assets", []):
    if asset.get("name") == candidate_name:
        print(json.dumps(
            {
                "version": release_version,
                "url": asset["browser_download_url"],
                "name": candidate_name,
            }
        ))
        break
else:
    raise SystemExit(1)
PY
)"; then
    printf 'failed to resolve flash-attn install target: no matching official wheel for base image %s in release %s\n' "$base_image" "$release_selector" >&2
    printf 'set FLASH_ATTN_INSTALL_TARGET explicitly, or choose a different FLASH_ATTN_VERSION\n' >&2
    exit 2
  fi

  FLASH_ATTN_INSTALL_TARGET="$("$host_python_cmd" - "$resolved" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(payload["url"])
PY
)"
  FLASH_ATTN_INSTALL_ARGS=""
  export FLASH_ATTN_INSTALL_TARGET
  export FLASH_ATTN_INSTALL_ARGS

  printf 'resolved official flash-attn wheel: %s\n' "$FLASH_ATTN_INSTALL_TARGET"
}

usage() {
  cat >&2 <<'EOF'
usage: ./build.sh [--force] [docker compose build args...]

options:
  --force    rebuild devel/runtime even if local images already exist

all other args are passed through to `docker compose build`
EOF
  exit 2
}

while (($# > 0)); do
  case "$1" in
    --force)
      force_rebuild=1
      ;;
    -h|--help)
      usage
      ;;
    *)
      compose_build_args+=("$1")
      ;;
  esac
  shift
done

if command -v docker-compose >/dev/null 2>&1; then
  compose_cmd=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
  compose_cmd=(docker compose)
else
  echo "docker compose / docker-compose not found" >&2
  exit 127
fi

resolve_pip_build_env
resolve_flash_attn_install_target

image_name_for() {
  case "$1" in
    devel)
      printf '%s\n' "${DEVEL_SOURCE_IMAGE:-hey3d/flashattn-devel:latest}"
      ;;
    runtime)
      printf '%s\n' "${RUNTIME_SOURCE_IMAGE:-hey3d/flashattn-runtime:latest}"
      ;;
    *)
      echo "unsupported flavor: $1" >&2
      exit 2
      ;;
  esac
}

confirm_rebuild() {
  local image_name="$1"

  if [[ $force_rebuild -eq 1 ]]; then
    return 0
  fi

  if ! docker image inspect "$image_name" >/dev/null 2>&1; then
    return 0
  fi

  if [[ ! -t 0 ]]; then
    printf 'skip build for %s (already exists, use --force to rebuild)\n' "$image_name"
    return 1
  fi

  local answer=""
  read -r -p "镜像 ${image_name} 已存在，是否重新 build? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES|Yes)
      return 0
      ;;
    *)
      printf 'skip build for %s\n' "$image_name"
      return 1
      ;;
  esac
}

build_service() {
  local service_name="$1"
  "${compose_cmd[@]}" build "${compose_build_args[@]}" "$service_name"
}

devel_image="$(image_name_for devel)"
runtime_image="$(image_name_for runtime)"
rebuilt_devel=0

if confirm_rebuild "$devel_image"; then
  build_service flashattn-devel
  rebuilt_devel=1
fi

if [[ $rebuilt_devel -eq 1 ]]; then
  printf 'rebuild flashattn-runtime because %s was rebuilt\n' "$devel_image"
  build_service flashattn-runtime
elif confirm_rebuild "$runtime_image"; then
  build_service flashattn-runtime
fi

tag_one() {
  local flavor="$1"
  local source_image=""

  case "$flavor" in
    devel)
      source_image="$devel_image"
      ;;
    runtime)
      source_image="$runtime_image"
      ;;
    *)
      echo "unsupported flavor: $flavor" >&2
      exit 2
      ;;
  esac

  docker image inspect "$source_image" >/dev/null

  local torch_label="" cuda_label="" cudnn_label="" flash_attn_label=""
  while IFS='=' read -r key value; do
    case "$key" in
      torch)
        torch_label="$value"
        ;;
      cuda)
        cuda_label="$value"
        ;;
      cudnn)
        cudnn_label="$value"
        ;;
      flash_attn)
        flash_attn_label="$value"
        ;;
    esac
  done < <(
    docker run --rm --entrypoint python "$source_image" -c '
import importlib.metadata
import torch

def torch_minor(version: str) -> str:
    base = version.split("+", 1)[0]
    parts = base.split(".")
    return ".".join(parts[:2])

def cudnn_major(version: int | None) -> str:
    if version is None:
        return "unknown"
    if version >= 100000:
        return str(version // 10000)
    if version >= 10000:
        return str(version // 10000)
    return str(version // 1000)

print(f"torch={torch_minor(torch.__version__)}")
print(f"cuda={torch.version.cuda or '\''unknown'\''}")
print(f"cudnn={cudnn_major(torch.backends.cudnn.version())}")
print(f"flash_attn={importlib.metadata.version('\''flash-attn'\'')}")
'
  )

  local target_tag target_image
  target_tag="${flash_attn_label}-torch${torch_label}-cuda${cuda_label}-cudnn${cudnn_label}-${flavor}"
  target_image="${target_repository}:${target_tag}"

  docker tag "$source_image" "$target_image"
  printf '%s -> %s\n' "$source_image" "$target_image"
}

tag_one devel
tag_one runtime
