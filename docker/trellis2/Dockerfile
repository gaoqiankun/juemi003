ARG FLASHATTN_DEVEL_IMAGE=cubie3d/flashattn-devel:latest
ARG FLASHATTN_RUNTIME_IMAGE=cubie3d/flashattn-runtime:latest

FROM ${FLASHATTN_DEVEL_IMAGE} AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    ffmpeg \
    libjpeg-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel

ARG TRELLIS2_REPO_URL=https://github.com/microsoft/TRELLIS.2.git
ARG TRELLIS2_REF=main
ARG TORCH_CUDA_ARCH_LIST=8.0;8.6;8.9;9.0
RUN git clone --recursive --branch ${TRELLIS2_REF} ${TRELLIS2_REPO_URL} /opt/TRELLIS.2

ENV PYTHONPATH=/opt/TRELLIS.2 \
    CUDA_HOME=/usr/local/cuda \
    FORCE_CUDA=1 \
    TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}

RUN python - <<'PY'
import os

import torch
from torch.utils.cpp_extension import _get_cuda_arch_flags

arch_list = os.environ.get("TORCH_CUDA_ARCH_LIST", "")
flags = _get_cuda_arch_flags()
print(
    {
        "torch_version": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "arch_list": arch_list,
        "cuda_flags": flags,
    }
)
if not flags:
    raise SystemExit("TORCH_CUDA_ARCH_LIST produced no CUDA arch flags")
PY

RUN python -m pip install \
      imageio \
      imageio-ffmpeg \
      tqdm \
      easydict \
      opencv-python-headless \
      trimesh \
      "transformers<5" \
      tensorboard \
      pandas \
      lpips \
      zstandard \
      pillow \
      kornia \
      packaging \
      timm

RUN python -m pip install \
      pybind11 \
      diffusers \
      einops \
      accelerate \
      omegaconf \
      pymeshlab \
      pygltflib \
      xatlas \
      rembg \
      onnxruntime \
      scikit-image

RUN git clone https://github.com/Tencent/Hunyuan3D-2 /opt/Hunyuan3D-2 && \
    cd /opt/Hunyuan3D-2 && \
    python -m pip install -e .

RUN cd /opt/Hunyuan3D-2/hy3dgen/texgen/custom_rasterizer && \
    python setup.py install

RUN cd /opt/Hunyuan3D-2/hy3dgen/texgen/differentiable_renderer && \
    python setup.py install

RUN git clone https://github.com/stepfun-ai/Step1X-3D /opt/Step1X-3D

RUN python - <<'PY'
from pathlib import Path

target = Path(
    "/opt/Step1X-3D/step1x3d_geometry/models/conditional_encoders/"
    "dinov2_with_registers/modeling_dinov2_with_registers.py"
)
content = target.read_text()

if "def initialize_weights(self):" in content:
    print("Step1X-3D DINOv2 patch already present")
    raise SystemExit(0)

# Override initialize_weights to no-op: newer transformers added this method
# which calls _init_weights on all modules including those with weight=None.
# When loading from pretrained the random init is overwritten anyway.
old = "    def _init_weights(self, module: Union[nn.Linear, nn.Conv2d, nn.LayerNorm]) -> None:"
new = (
    "    def initialize_weights(self):\n"
    "        pass  # skip random init; weights are loaded from pretrained checkpoint\n"
    "\n"
    "    def _init_weights(self, module: Union[nn.Linear, nn.Conv2d, nn.LayerNorm]) -> None:"
)
if old not in content:
    raise SystemExit("Failed to patch Step1X-3D DINOv2: anchor not found")

target.write_text(content.replace(old, new, 1))
print(f"patched {target}")
PY

RUN python - <<'PY'
from pathlib import Path

target = Path("/opt/Step1X-3D/step1x3d_geometry/models/pipelines/pipeline.py")
content = target.read_text()

# Fix inverted condition in check_inputs: Step1X-3D raises when image IS a valid
# type (torch.Tensor / PIL.Image), should raise when it is NOT.
old = "        elif isinstance(image, (torch.Tensor, PIL.Image.Image)):\n            raise ValueError(\n                \"Input image must be a `torch.Tensor` or `PIL.Image.Image`.\"\n            )"
new = "        elif not isinstance(image, (torch.Tensor, PIL.Image.Image)):\n            raise ValueError(\n                \"Input image must be a `torch.Tensor` or `PIL.Image.Image`.\"\n            )"

if old not in content:
    raise SystemExit("Failed to patch Step1X-3D check_inputs: anchor not found")

target.write_text(content.replace(old, new, 1))
print(f"patched {target}")
PY

RUN python -m pip install \
    "pytorch-lightning==2.6.1" \
    jaxtyping \
    typeguard \
    mosaicml-streaming \
    wandb

RUN cd /opt/Step1X-3D/step1x3d_texture/custom_rasterizer && \
    python setup.py install

RUN cd /opt/Step1X-3D/step1x3d_texture/differentiable_renderer && \
    python setup.py install

RUN python -m pip install "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"

RUN TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST} \
    FORCE_CUDA=1 \
    CUDA_HOME=/usr/local/cuda \
    python -m pip install /opt/TRELLIS.2/o-voxel --no-build-isolation

RUN git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git /tmp/nvdiffrast && \
    python -m pip install /tmp/nvdiffrast --no-build-isolation && \
    rm -rf /tmp/nvdiffrast

RUN git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git /tmp/nvdiffrec && \
    python -m pip install /tmp/nvdiffrec --no-build-isolation && \
    rm -rf /tmp/nvdiffrec

RUN git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/CuMesh && \
    python -m pip install /tmp/CuMesh --no-build-isolation && \
    rm -rf /tmp/CuMesh

RUN git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/FlexGEMM && \
    python -m pip install /tmp/FlexGEMM --no-build-isolation && \
    rm -rf /tmp/FlexGEMM

FROM ${FLASHATTN_RUNTIME_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    ffmpeg \
    libjpeg-dev \
    libgl1 \
    libglib2.0-0 \
    libopengl0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/conda /opt/conda
COPY --from=builder /opt/TRELLIS.2 /opt/TRELLIS.2
COPY --from=builder /opt/Hunyuan3D-2 /opt/Hunyuan3D-2
COPY --from=builder /opt/Step1X-3D /opt/Step1X-3D

ENV PYTHONPATH=/opt/TRELLIS.2:/opt/Hunyuan3D-2:/opt/Step1X-3D \
    CC=/usr/bin/gcc \
    CXX=/usr/bin/g++
