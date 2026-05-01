# Model Loading Architecture Refactor

**status**: backlog  
**created**: 2026-04-15  
**priority**: high

## Background

本次会话通过深度讨论识别出模型加载架构的根本性问题。当前代码直接继承了 HuggingFace 的设计哲学，没有针对我们的使用场景做清理。

## 核心问题

### 1. `from_pretrained` 是 HF 遗留物

三个模型（Trellis2、HunyuanY3D、Step1X3D）的 provider 都使用 `from_pretrained(path)` 加载。这个模式假设：
- 模型是公开分发的，任何人下载即可跑
- 配置随权重走（`pipeline.json`）
- 代码是通用的，不了解具体模型

我们的实际情况完全不同：我们 fork 了代码，provider 就是模型的说明书，我们知道跑的是哪个模型。`from_pretrained` 在我们这里只有一个有用的操作：**从路径加载权重张量**。其余的（读 JSON、按 JSON 实例化 sub-model）是不需要的逻辑。

**目标**：provider 直接加载权重文件（`safetensors.load_file` / `torch.load`），加载哪些文件、加载到哪个类，全由 provider 代码决定。

### 2. `pipeline.json` 不应作为运行时配置源

`pipeline.json` 是从上游 HF repo 随权重一起下载的文件。当前代码在 `from_pretrained` 里读取它来决定：
- 哪些 sub-model、路径在哪
- sampler 参数
- normalization 参数
- `low_vram` 等运行时参数

问题：
- 用户可以任意修改这个文件，改乱了我们的代码直接崩
- 上游更新格式我们也会崩
- 运行时行为参数（`low_vram`）不该放在模型分发文件里
- 重新下载会覆盖我们对这个文件的任何修改

**目标**：
- `pipeline.json` 仅用于**下载后校验**（验证期望的权重文件存在、schema 符合预期）
- 运行时参数（`low_vram` 等）全部来自我们的 DB（`_SEED_MODELS`）
- Sub-model 路径由 provider 代码硬编码，不从 JSON 读

### 3. 下载后缺少校验步骤

当前下载完成后直接标记 `download_status = done`，没有验证：
- 期望的权重文件是否都存在
- `pipeline.json` schema 是否符合预期
- 文件完整性（大小/checksum）

问题：下载损坏或版本不对，要到 `from_pretrained` 运行时才报错，报的是莫名其妙的 KeyError 或 FileNotFoundError。

**目标**：`WeightManager` 下载完成后做结构校验，失败则标记 `download_error`，而非标记 done。

### 4. 三种下载源的实际价值

- `huggingface`：主要来源，`snapshot_download` 拉整个 repo
- `local`：有价值，权重已在本地直接指路径
- `url`（zip/tar.gz）：实际上没人用，要求对方把 HF 格式的目录打成 zip，增加了复杂度

三种源落地后目录结构必须和 HF repo 一致，"解耦 HF"只是传输层解耦，不是格式解耦。

## 具体改动范围

### Phase 1：运行时参数从 DB 读（低风险，可先做）

- `low_vram` 加入 `_SEED_MODELS`，三个模型默认 `True`
- Provider 加载时从 model config 读 `low_vram`，不读 `pipeline.json`
- Trellis2：`pipeline.low_vram = model_config.get('low_vram', True)` 覆盖 `args` 里的值
- HunyuanY3D / Step1X3D：实现 CPU offloading（参考 Trellis2 模式）

同时修复 VRAM 显示 bug：
- `low_vram=True` → `weight_vram_mb = 0`
- `_normalize_vram_mb` 接受 0 为有效值

### Phase 2：下载后校验（中风险）

每个 provider 定义 `validate_downloaded(model_path: str) -> None`，检查：
- 必要的权重文件是否存在（provider 代码里写死文件名列表）
- `pipeline.json`（如果还用）schema 基本字段存在

`WeightManager.download()` 完成后调用 `validate_downloaded`，失败则 `update_download_error`。

### Phase 3：移除 `from_pretrained`（高风险，需仔细设计）

- Provider 直接加载权重张量，不依赖 `pipeline.json`
- Sub-model 文件名列表硬编码在 provider 里
- Sampler 参数、normalization 参数迁移到 provider 代码或 `_SEED_MODELS`
- 删除 `pipeline.json` 的运行时读取逻辑

## 当前 `low_vram` 配置现状

| 模型 | 当前配置来源 | 默认值 | 实现状态 |
|------|------------|--------|---------|
| Trellis2 | `pipeline.json` → `args.get('low_vram', True)` | True | 完整实现，每个 sub-model 推理前 `.to(device)` 推理后 `.cpu()` |
| HunyuanY3D | 无 | N/A | 直接 `.cuda()`，无 offloading |
| Step1X3D | 无 | N/A | 直接 `.to("cuda")`，无 offloading |

## 关联的 VRAM 显示 bug（需在 Phase 1 一起修）

1. `_normalize_vram_mb(0)` 返回 None → Trellis2（low_vram=True，weight=0）fallback 到 `vram_gb * 0.75 ≈ 17.6G`
2. `_on_weight_measured` 更新 DB 但不更新 allocator `budget.allocations[model]`
3. `_SEED_MODELS` 里 `weight_vram_mb` 值错误（Trellis2=16000 应为 0）
4. Weight VRAM 用 EMA 平滑是错误的（deterministic 值不应 EMA）

## 文件影响范围

**Phase 1**：
- `storage/model_store.py` — `_SEED_MODELS` 加 `low_vram` 字段，修正 `weight_vram_mb`
- `api/helpers/vram.py` — `_normalize_vram_mb` 接受 0；移除 EMA for weight
- `model/trellis2/provider.py` — 加载时用 DB `low_vram` 覆盖
- `model/hunyuan3d/provider.py` — 实现 low_vram offloading
- `model/step1x3d/provider.py` — 实现 low_vram offloading
- `engine/model_registry.py` — `_on_weight_measured` 同步更新 allocator

**Phase 2**：
- `engine/weight_manager.py` — 下载完成后调 validate
- 每个 provider — 新增 `validate_downloaded` 静态方法

**Phase 3**（独立大任务）：
- 三个模型的 provider + pipeline 代码大改
