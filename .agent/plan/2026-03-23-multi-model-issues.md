# 多模型支持遗留问题
Date: 2026-03-23
Status: planning

## Goal
让 HunYuan3D-2 和 Step1X-3D 在 Docker 部署中真正可用，修复模型加载链路的设计缺陷。

## 问题清单

### P1 · 模型加载失败后不可重试

**文件**：`engine/model_registry.py` 第 94 行

```python
if entry.state in {"loading", "ready", "error"}:
    return
```

模型加载失败后 `state="error"`，后续所有 `load()` 调用直接 return，永远不会重试。必须重启服务才能恢复。

需要设计：error 状态允许重新触发加载，同时处理并发（多个任务同时请求一个 error 模型不能重复触发加载）。

### P2 · 用户可以提交任务到未就绪的模型

用户侧能选到 `model_definitions` 表里的所有模型（HunYuan3D-2、Step1X-3D），不管权重是否已下载、依赖是否已安装。提交后在运行时才发现加载失败，任务直接废掉。

应该有机制让用户侧只能选已就绪（或至少有可能就绪）的模型。

### P3 · HunYuan3D-2 依赖未集成到 Docker 镜像

当前 Dockerfile 基于 `TRELLIS2_IMAGE`，只有 TRELLIS2 的依赖。HunYuan3D-2 需要：
- `hy3dgen` 包（`pip install -e .` 从 https://github.com/Tencent/Hunyuan3D-2）
- `libopengl0` 系统包（pymeshlab 需要）
- 2 个 CUDA 扩展编译（`texgen/custom_rasterizer` + `texgen/differentiable_renderer`，材质生成用，需要在构建阶段编译，运行时容器编译不了）

### P4 · Step1X-3D 依赖未集成且冲突风险高

`step1x3d_geometry` + `step1x3d_texture` 需要：
- pytorch3d、kaolin 0.17.0、nvdiffrast、cupy-cuda12x
- 2 个 CUDA 扩展编译（同样是 custom_rasterizer + differentiable_renderer）
- requirements.txt 版本 pinned 很严格（`huggingface-hub==0.26.2`、`transformers==4.48.0`、`diffusers==0.32.2`），和现有环境冲突风险高

### P5 · 模型权重下载无保障

`from_pretrained` 内部调用 `huggingface_hub.snapshot_download`，容器网络到 HF 不稳定时（SSL 断连、超时）下载失败，没有足够的重试和恢复机制。TRELLIS2 权重碰巧下载成功了并缓存在 `HF_HOME=/data/huggingface`，HunYuan3D-2 没缓存所以失败。

### P6 · hy3dgen 有自己的缓存路径

`hy3dgen/shapegen/utils.py` 的 `smart_load_model` 先查 `HY3DGEN_MODELS`（默认 `~/.cache/hy3dgen`），找不到才调 `snapshot_download`（下载到 HF 缓存）。两套缓存路径并存，需要统一或配置。

## 依赖分析结果

### HunYuan3D-2 推理实际需要的第三方包

通过 import 链分析确认（完整列表见 `gen3d/hy3d_deps.txt`）：

`accelerate` `diffusers` `einops` `cv2`(opencv) `flash_attn` `huggingface_hub` `numpy` `pymeshlab` `safetensors` `scipy` `skimage`(scikit-image) `tokenizers` `transformers` `torch` `torchvision` `triton` `tqdm` `trimesh` `xatlas` `yaml`(PyYAML)

setup.py 里多余的（推理不需要）：gradio、fastapi、uvicorn、onnxruntime。

rembg 未出现在 import 链中（可能是运行时按需 import 用于背景去除，待验证）。

### Step1X-3D

未实际安装测试，仅查看了 GitHub README 和 requirements.txt。

## 环境信息

容器内当前环境：
- Python 3.11.11 (conda-forge)
- PyTorch 2.6.0+cu124
- CUDA 12.4
- GPU: NVIDIA RTX A6000 (48GB)

## Notes
- `hy3dgen` 已在运行中的容器里手动安装成功（`pip install -e .`），import 正常，但权重未下载、CUDA 扩展未编译
- 容器内无法编译 CUDA 扩展，需在 Dockerfile 构建阶段完成
- HunYuan3D-2 形状生成需要 6GB VRAM，加材质 16GB；TRELLIS2 已占用部分显存
