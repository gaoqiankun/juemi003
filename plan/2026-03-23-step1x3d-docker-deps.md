# Step1X-3D 依赖集成到 Trellis2 Docker 基础镜像
Date: 2026-03-23
Status: done

## Goal

在 `docker/trellis2/Dockerfile` 中追加 Step1X-3D 运行所需的依赖，使同一镜像可同时跑
Trellis2、HunYuan3D-2、Step1X-3D 三个模型。

## 调研结论

**官方 requirements.txt 中的重型包（kaolin、pytorch3d、torch-cluster、deepspeed、open3d）
推理时完全不需要，均为训练/Demo UI 依赖，不装。**

实际 import 路径（从我们的 provider 出发）：
- `step1x3d_geometry.models.pipelines.pipeline`
  → torch、trimesh、rembg、numpy、diffusers、transformers、huggingface_hub
- `step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline`
  → torch、torchvision、trimesh、xatlas、scipy、diffusers、transformers、nvdiffrast（已有）

已在镜像中（trellis2 原有 + HunYuan3D-2 追加）：
- torch、torchvision、trimesh、numpy、scipy、diffusers、transformers、xatlas
- nvdiffrast、einops、accelerate、omegaconf、pybind11、pymeshlab、pygltflib

**新增的包：**
- `rembg`（geometry pipeline 直接 import）
- `onnxruntime`（rembg 运行时依赖）
- `scikit-image`（texture pipeline 依赖，检查 hy3d_deps.txt 里有 skimage，但 trellis2
  Dockerfile 未显式安装，可能来自其他包的传递依赖，显式装一下保险）

**C++ 扩展编译（builder stage，需要 CUDA devel 环境）：**
- `step1x3d_texture/custom_rasterizer`
- `step1x3d_texture/differentiable_renderer`

**安装方式：与 HunYuan3D-2 保持一致**
- `pip install -e .`（editable install，源码需在 runtime 保留）
- Clone 到 `/opt/Step1X-3D`
- runtime stage COPY + PYTHONPATH 追加

## Changes

`docker/trellis2/Dockerfile` builder stage（HunYuan3D-2 安装块之后追加）：

1. pip 安装新包：`rembg`、`onnxruntime`、`scikit-image`

2. Clone 并安装 Step1X-3D：
   ```
   git clone https://github.com/stepfun-ai/Step1X-3D /opt/Step1X-3D
   cd /opt/Step1X-3D && pip install -e .
   ```

3. 编译两个 C++ 扩展：
   ```
   cd /opt/Step1X-3D/step1x3d_texture/custom_rasterizer && python setup.py install
   cd /opt/Step1X-3D/step1x3d_texture/differentiable_renderer && python setup.py install
   ```

`docker/trellis2/Dockerfile` runtime stage：

1. `COPY --from=builder /opt/Step1X-3D /opt/Step1X-3D`
2. PYTHONPATH 更新为：`/opt/TRELLIS.2:/opt/Hunyuan3D-2:/opt/Step1X-3D`

## 验收标准

- `docker build -f docker/trellis2/Dockerfile .` 成功无报错
- 容器内以下均正常：
  ```
  python -c "from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline; print('ok')"
  python -c "from step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline import Step1X3DTexturePipeline; print('ok')"
  ```
- 原有验收不退化：
  ```
  python -c "from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline; print('ok')"
  python -c "import flash_attn; print(flash_attn.__version__)"
  ```

## Notes

- Step1X-3D 官方要求 PyTorch 2.5.1，我们强制对齐到 2.6.0。
  实际推理依赖（diffusers、transformers、nvdiffrast 等）均无版本绑定，无兼容性风险。
- custom_rasterizer 和 differentiable_renderer 与 HunYuan3D-2 中同名扩展可能存在冲突
  （同名 .so 覆盖问题），AI Coder 执行时需确认两套扩展的模块名是否相同，
  若冲突需调整安装顺序或隔离安装路径。
- rembg 依赖 onnxruntime，构建时会下载 ONNX 模型文件（背景去除模型），
  如网络受限需预先处理。

## Execution

- 已按 Changes 完成 `docker/trellis2/Dockerfile` 修改（Step1X 依赖、源码安装、扩展编译、runtime COPY/PYTHONPATH）。
- 本地当前环境不是最终 Docker 构建验收环境，未在此机完成最终 build/import 验收。
- 验收建议在 CI 或指定构建机执行：
  - `docker build -f docker/trellis2/Dockerfile .`
  - `python -c "from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline; print('ok')"`
  - `python -c "from step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline import Step1X3DTexturePipeline; print('ok')"`
