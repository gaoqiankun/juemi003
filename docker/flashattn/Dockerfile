ARG BASE_IMAGE=pytorch/pytorch:2.6.0-cuda12.4-cudnn9-devel
FROM ${BASE_IMAGE}

ARG FLASH_ATTN_INSTALL_TARGET=flash-attn
ARG FLASH_ATTN_INSTALL_ARGS=--no-build-isolation
ARG TORCH_CUDA_ARCH_LIST=
ARG MAX_JOBS=8
ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_TRUSTED_HOST=
ARG PIP_DEFAULT_TIMEOUT=120

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    CUDA_HOME=/usr/local/cuda \
    MAX_JOBS=${MAX_JOBS}

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install packaging psutil ninja

RUN python - <<'PY'
import json
import os
import torch

print(
    json.dumps(
        {
            "torch_version": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "cuda_home": os.environ.get("CUDA_HOME"),
            "flash_attn_install_target": os.environ.get("FLASH_ATTN_INSTALL_TARGET"),
            "flash_attn_install_args": os.environ.get("FLASH_ATTN_INSTALL_ARGS"),
            "torch_cuda_arch_list": os.environ.get("TORCH_CUDA_ARCH_LIST"),
        },
        indent=2,
    )
)
PY

ENV FLASH_ATTN_INSTALL_TARGET=${FLASH_ATTN_INSTALL_TARGET} \
    FLASH_ATTN_INSTALL_ARGS=${FLASH_ATTN_INSTALL_ARGS} \
    TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}

RUN set -eu; \
    if [ -n "${TORCH_CUDA_ARCH_LIST}" ]; then \
      TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}" FORCE_CUDA=1 CUDA_HOME=/usr/local/cuda \
        python -m pip install ${FLASH_ATTN_INSTALL_ARGS} "${FLASH_ATTN_INSTALL_TARGET}"; \
    else \
      python -m pip install ${FLASH_ATTN_INSTALL_ARGS} "${FLASH_ATTN_INSTALL_TARGET}"; \
    fi

RUN python -m pip show flash-attn

WORKDIR /workspace

CMD ["bash"]
