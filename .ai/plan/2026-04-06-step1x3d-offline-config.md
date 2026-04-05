# Step1X-3D DINOv2 Config Offline
Date: 2026-04-06
Status: approved

## Goal

消除 Step1X-3D 加载时对 HuggingFace 网络的两个依赖，实现完全离线加载。

## 背景

经部署机实测确认：
- 实际使用的 encoder：`Dinov2Encoder`（`dinov2_encoder.py`），`dino_type = "facebook/dinov2-with-registers-large"`
- DINOv2 权重已在 snapshot 内（`visual_encoder/diffusion_pytorch_model.safetensors`）
- T5/caption_encoder 已是 null，不加载
- 触发 HF 网络请求的只有 2 处，均在 `dinov2_encoder.py`

## 需要 bundle 的文件

来源：`facebook/dinov2-with-registers-large`
- `config.json`（架构配置，约 2 KB）
- `preprocessor_config.json`（图像预处理配置，约 1 KB）

存放位置：`model/step1x3d/configs/facebook--dinov2-with-registers-large/`

## 文件变更

**新增**
- `model/step1x3d/configs/facebook--dinov2-with-registers-large/config.json`
- `model/step1x3d/configs/facebook--dinov2-with-registers-large/preprocessor_config.json`

**修改 `model/step1x3d/pipeline/step1x3d_geometry/models/conditional_encoders/dinov2_encoder.py`**
- 文件顶部定义本地 configs 路径常量：
  ```python
  _CONFIGS_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "configs"
  ```
  （即 `model/step1x3d/configs/`）
- 将触发 HF 网络请求的两处改为本地路径：
  1. `Dinov2WithRegistersModel.config_class.from_pretrained(self.cfg.dino_type)` → `from_pretrained(_CONFIGS_DIR / "facebook--dinov2-with-registers-large")`
  2. `AutoImageProcessor.from_pretrained(self.cfg.dino_type)` → `from_pretrained(_CONFIGS_DIR / "facebook--dinov2-with-registers-large")`
- 仅修改 `dino_type = "facebook/dinov2-with-registers-large"` 对应的分支（`"reg" in self.cfg.dino_type` 且 `"large" in self.cfg.dino_type`），其余分支暂不改动

**不改动**
- `dinov2_clip_encoder.py`（当前模型不使用）
- `t5_encoder.py`
- `provider.py`
- 任何前端文件或 `.ai/` 文件

## 操作步骤

1. 用 `huggingface_hub` 下载两个文件：
   ```python
   from huggingface_hub import hf_hub_download
   hf_hub_download("facebook/dinov2-with-registers-large", "config.json", local_dir="model/step1x3d/configs/facebook--dinov2-with-registers-large")
   hf_hub_download("facebook/dinov2-with-registers-large", "preprocessor_config.json", local_dir="model/step1x3d/configs/facebook--dinov2-with-registers-large")
   ```
2. 修改 `dinov2_encoder.py`
3. 运行 `uv run ruff check .` 确认无新增 issue

## Acceptance Criteria

- [ ] `model/step1x3d/configs/facebook--dinov2-with-registers-large/config.json` 存在且内容有效
- [ ] `model/step1x3d/configs/facebook--dinov2-with-registers-large/preprocessor_config.json` 存在且内容有效
- [ ] `dinov2_encoder.py` 中 `Dinov2WithRegistersModel.config_class.from_pretrained` 和 `AutoImageProcessor.from_pretrained` 均改为本地路径
- [ ] `uv run ruff check .` 无新增 issue
- [ ] `uv run python -m pytest tests -q` 无新增 failure

## Out of scope

- `dinov2_clip_encoder.py` 其他分支（非当前模型使用路径）
- T5 / caption_encoder 改动
- 其他 DINOv2 变体（dinov2-base、dinov2-with-registers-base）
