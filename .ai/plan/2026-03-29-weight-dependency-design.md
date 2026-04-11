# Weight Dependency Management — 完整设计方案
Date: 2026-03-29 / Status: design-review-v3（已按第四轮 Evaluator 意见修订）
Status: done

---
## 一、问题陈述

当前 WeightManager 只下载"主模型 repo"，但三个 Provider 在加载时还依赖外部权重，这些依赖在模型 Load 时才触发网络下载，破坏了"权重获取与推理分离"的设计目标。

### 已确认的外部依赖（代码扫描结果）

| Provider | 依赖 ID | 来源 | 硬编码位置 | 估算大小 |
|----------|---------|------|-----------|---------|
| TRELLIS2 | `dinov2-vitl14` | `torch.hub: facebookresearch/dinov2` | `pipeline/modules/image_feature_extractor.py:17`（DinoV2FeatureExtractor） | ~1.2 GB |
| TRELLIS2 | `birefnet` | `HF: ZhengPeng7/BiRefNet` | `pipeline/pipelines/rembg/BiRefNet.py:11` | ~0.5 GB |
| Step1X-3D | `sdxl-base-1.0` | `HF: stabilityai/stable-diffusion-xl-base-1.0` | `pipeline/step1x3d_texture/pipelines/step1x_3d_texture_synthesis_pipeline.py:37` | ~7 GB |
| Step1X-3D | `sdxl-vae-fp16` | `HF: madebyollin/sdxl-vae-fp16-fix` | 同上 `:38` | ~0.3 GB |
| Step1X-3D | `birefnet` | `HF: ZhengPeng7/BiRefNet` | 同上 `:347`（lazy） | ~0.5 GB（共享）|
| HunYuan3D | —（无） | conditioner 权重从 checkpoint 加载，已包含在主 repo snapshot 中 | — | — |

**关键发现**：
- `birefnet` 被 TRELLIS2 和 Step1X-3D 共享，应只下载一次
- Step1X-3D 依赖 SDXL Base（~7 GB），这是重量级外部依赖
- TRELLIS2 的 DINOv2 通过 torch.hub 下载，绕开 HF 生态，需要统一

**代码扫描补充说明**：

**TRELLIS2 DinoV2 vs DinoV3**：`image_feature_extractor.py` 中同时存在两个类：
- `DinoV2FeatureExtractor`（:17）：`torch.hub.load('facebookresearch/dinov2', ...)` — 有外部依赖
- `DinoV3FeatureExtractor`（:60）：`DINOv3ViTModel.from_pretrained(model_name)` — 已 HF 风格，model_name 由 config 注入

实际使用哪个由模型权重目录里的 `pipeline.json` 中 `args['image_cond_model']['name']` 字段决定。代码仓库里没有此文件。设计文档基于当前已知信息假设 TRELLIS2 v2 使用 DinoV2 路径，**B2 阶段开工前须先确认 pipeline.json 中的实际值**。若生产模型使用 DinoV3，则 `dinov2-vitl14` 依赖声明可删除。

**HunYuan3D 外部依赖确认**：conditioner 的 `ImageEncoder.__init__` 中 `from_pretrained(version)` 的 `version` 值来自模型 repo 内的 config.yaml，不是远程 HF ID。texgen 工具类（`alignImg4Tex_utils.py` 等）含硬编码 HF ID，但经代码路径分析这些类不在正常 3D 生成推理路径上，不会被触发。`dehighlight_utils.py` 和 `multiview_utils.py` 在正常推理路径上但使用本地子路径（来自 checkpoint），不联网。**HunYuan3D 无外部依赖结论成立**。

**Step1X-3D geometry encoder 潜在外部依赖（待 B2 前验证）**：geometry 侧的三个条件编码器在初始化时有 fallback 分支会触发网络请求：

| 文件 | 硬编码 fallback HF ID | 触发条件 |
|------|----------------------|---------|
| `conditional_encoders/dinov2_encoder.py:91` | `facebook/dinov2-base` | `cfg.pretrained_dino_name_or_path` 未指向本地路径 |
| `conditional_encoders/dinov2_encoder.py:102,114` | `facebook/dinov2-with-registers-base` | 同上（registers 变体） |
| `conditional_encoders/t5_encoder.py:84` | `google-t5/t5-small` | `cfg.pretrained_t5_name_or_path` 未指向本地路径 |
| `conditional_encoders/t5_encoder.py:90` | `google-t5/t5-base` | 同上 |
| `conditional_encoders/dinov2_clip_encoder.py:85` | `openai/clip-vit-large-patch14` | `cfg.pretrained_clip_name_or_path` 未指向本地路径 |
| `conditional_encoders/dinov2_clip_encoder.py:120,131,143` | 多个 `facebook/dinov2-*` | 同上 |

以上 fallback 分支是否会被触发，取决于 Step1X-3D 模型 repo 的 `config.yaml` 中这些字段的实际值：
- 如果字段指向 repo 内子路径（如 `./encoders/dino`）→ 本地加载，无外部依赖
- 如果字段为空或指向 HF repo ID → 触发网络请求，需纳入 dep 管理

**B2 开工前必须检查 Step1X-3D 模型 repo 的 config.yaml，确认以上字段是否为本地路径**。若不是，则需新增 dep 声明（`dinov2-base`、`t5-encoder`、`clip-vit-l14` 等）。

---

## 二、设计目标

1. **完全离线运行**：WeightManager 完成后，模型 Load 全程无网络请求
2. **依赖共享**：相同依赖（如 BiRefNet）跨多个 Provider 实例只存一份
3. **Provider 与获取解耦**：Provider 只声明"需要什么"，不管"怎么获取"
4. **统一下载通道**：所有权重（含原 torch.hub 依赖）均通过 HF snapshot_download 获取
5. **Admin 可见**：用户能在界面上看到每个模型的完整依赖状态

---

## 三、架构概览

```
Admin 添加模型
    ↓
WeightManager.download(model_id)
    ① snapshot_download(main_repo) → MODEL_CACHE_DIR/{model_id}/
    ② for dep in Provider.dependencies():
         dep_cache.get_or_download(dep) → HF_HOME/hub/...
    ③ 全部完成 → model_definitions.download_status = 'done'
    ④ 任一 dep 失败 → model_definitions.download_status = 'error'
    ↓
Admin 点 Load
    ↓
build_model_runtime → 读 resolved_path + dep_paths
    ↓（设置 HF_HUB_OFFLINE=1 作为兜底）
Provider.from_pretrained(local_path, dep_paths={...})
    → 纯本地 I/O，无网络调用
    → 子进程（ProcessGPUWorker）通过 WorkerProcessConfig 获得 dep_paths
```

---

## 四、数据模型

### 4.1 新增表：`dep_cache`（全局共享依赖缓存）

```sql
CREATE TABLE IF NOT EXISTS dep_cache (
    dep_id          TEXT PRIMARY KEY,   -- 规范 ID，如 "birefnet"、"dinov2-vitl14"
    hf_repo_id      TEXT NOT NULL,      -- HF repo，如 "ZhengPeng7/BiRefNet"
    resolved_path   TEXT,               -- 下载完成后的本地路径
    download_status TEXT NOT NULL DEFAULT 'pending',  -- pending|downloading|done|error
    download_progress INTEGER NOT NULL DEFAULT 0,
    download_speed_bps INTEGER NOT NULL DEFAULT 0,
    download_error  TEXT
);
```

### 4.2 新增表：`model_dep_requirements`（模型与依赖的关联）

```sql
CREATE TABLE IF NOT EXISTS model_dep_requirements (
    model_id TEXT NOT NULL REFERENCES model_definitions(id) ON DELETE CASCADE,
    dep_id   TEXT NOT NULL REFERENCES dep_cache(dep_id),
    PRIMARY KEY (model_id, dep_id)
);
```

### 4.3 `model_definitions` 无结构变更

`download_status='done'` 语义扩展为：主模型 + 所有依赖均已就绪。

---

## 五、Provider 依赖声明契约

### 5.1 数据结构

```python
@dataclass(frozen=True)
class ProviderDependency:
    dep_id: str       # 规范 ID，全局唯一，如 "birefnet"
    hf_repo_id: str   # HF repo ID，如 "ZhengPeng7/BiRefNet"
    description: str  # 人类可读描述，显示在 Admin UI
```

### 5.2 Provider 基类新增接口

**注意**：当前 `BaseModelProvider` 是 `Protocol`（duck typing），不支持带默认实现的方法。B2 阶段需将基类改为 `ABC`（或引入 Mixin），使 `dependencies()` 的默认空实现合法。

```python
from abc import ABC, abstractmethod

class BaseModelProvider(ABC):
    @classmethod
    def dependencies(cls) -> list[ProviderDependency]:
        """声明该 Provider 需要的所有外部依赖（不含主模型）。默认无依赖。"""
        return []

    @classmethod
    @abstractmethod
    def from_pretrained(
        cls,
        model_path: str,
        dep_paths: dict[str, str],  # {dep_id: resolved_local_path}
    ) -> "BaseModelProvider":
        ...
```

### 5.3 各 Provider 声明

**TRELLIS2**：
```python
@classmethod
def dependencies(cls) -> list[ProviderDependency]:
    return [
        ProviderDependency(
            dep_id="dinov2-vitl14",
            hf_repo_id="facebook/dinov2-large",
            description="DINOv2 ViT-L/14 visual feature extractor",
        ),
        ProviderDependency(
            dep_id="birefnet",
            hf_repo_id="ZhengPeng7/BiRefNet",
            description="Background removal model",
        ),
    ]
```

> B2 开工前须确认 pipeline.json 使用 DinoV2 还是 DinoV3；若为 DinoV3，删除 `dinov2-vitl14` 声明。

**Step1X-3D**：
```python
@classmethod
def dependencies(cls) -> list[ProviderDependency]:
    return [
        ProviderDependency(
            dep_id="sdxl-base-1.0",
            hf_repo_id="stabilityai/stable-diffusion-xl-base-1.0",
            description="SDXL base model for texture synthesis",
        ),
        ProviderDependency(
            dep_id="sdxl-vae-fp16",
            hf_repo_id="madebyollin/sdxl-vae-fp16-fix",
            description="SDXL VAE (fp16 fixed)",
        ),
        ProviderDependency(
            dep_id="birefnet",
            hf_repo_id="ZhengPeng7/BiRefNet",
            description="Background removal model",
        ),
    ]
```

**HunYuan3D**：
```python
@classmethod
def dependencies(cls) -> list[ProviderDependency]:
    return []  # 所有权重包含在主 repo 中
```

### 5.4 dep_paths 在 Provider 内部的注入方式

`from_pretrained(model_path, dep_paths)` 收到路径后，需将其传递给内部子组件。以各 Provider 为例：

- **TRELLIS2**：`pipeline.json` 在本地加载，`from_pretrained` 构造 pipeline 时将 `dep_paths["dinov2-vitl14"]` 和 `dep_paths["birefnet"]` 传入 `DinoV2FeatureExtractor` 和 `BiRefNet` 的构造函数（替换 torch.hub/HF 远程 ID）
- **Step1X-3D**：`Step1X3DTextureSynthesisPipeline.from_pretrained` 在构造 `Step1X3DTextureConfig` 时，将 `dep_paths["sdxl-base-1.0"]` / `dep_paths["sdxl-vae-fp16"]` 显式赋值给 `config.base_model` / `config.vae_model`（覆盖硬编码字符串），`dep_paths["birefnet"]` 在 BiRefNet lazy 初始化时传入
- **HunYuan3D**：无需传递

---

## 六、WeightManager 变更

### 6.1 新增 DepCacheStore

```python
class DepCacheStore:
    """管理 dep_cache 表的读写。并发安全：get_or_create 使用 INSERT OR IGNORE + SELECT。"""
    async def get_or_create(self, dep_id, hf_repo_id) -> dict
    async def update_status(self, dep_id, status)
    async def update_progress(self, dep_id, progress, speed_bps)
    async def update_done(self, dep_id, resolved_path)
    async def update_error(self, dep_id, error)
    async def get_all_for_model(self, model_id) -> list[dict]
```

**并发安全（记录创建）**：`get_or_create` 使用 `INSERT OR IGNORE INTO dep_cache(dep_id, hf_repo_id) VALUES(?,?)` 后 SELECT，依赖 SQLite 唯一约束保证幂等，无需应用层锁。

**并发安全（下载执行）**：两个模型同时添加（如 TRELLIS2 + Step1X-3D 都依赖 birefnet）时，必须保证 birefnet 只被下载一次。WeightManager 维护一个进程级 `_dep_locks: dict[str, asyncio.Lock]` 字典，每个 dep_id 对应一把锁：

```python
# WeightManager 内部
_dep_locks: dict[str, asyncio.Lock] = {}

async def _download_dep_once(self, dep: ProviderDependency):
    """确保同一 dep 只有一个协程在下载，其余等待结果。"""
    if dep.dep_id not in self._dep_locks:
        self._dep_locks[dep.dep_id] = asyncio.Lock()
    async with self._dep_locks[dep.dep_id]:
        # 加锁后再次检查状态（可能已被前一个协程下载完）
        dep_record = await self._dep_store.get(dep.dep_id)
        if dep_record["download_status"] == "done":
            return
        await self._do_snapshot_download(dep)
```

这样 TRELLIS2 和 Step1X-3D 的下载任务并发运行时，birefnet 锁保证只有一个实际执行下载，另一个等待后直接读取已完成的结果。

### 6.2 WeightManager.download() 扩展

```python
async def download(self, model_id, provider_type, weight_source, model_path):
    # 1. 下载主模型（现有逻辑不变）
    await self._download_main(model_id, weight_source, model_path)

    # 2. 获取该 Provider 的依赖列表
    provider_cls = get_provider_class(provider_type)
    deps = provider_cls.dependencies()

    # 3. 注册关联关系（幂等）
    for dep in deps:
        await self._dep_store.get_or_create(dep.dep_id, dep.hf_repo_id)
        await self._model_dep_store.link(model_id, dep.dep_id)

    # 4. 下载尚未完成的依赖（已 done 的跳过）
    for dep in deps:
        dep_record = await self._dep_store.get(dep.dep_id)
        if dep_record["download_status"] == "done":
            continue
        try:
            await self._download_dep(dep)
        except Exception as e:
            # dep 失败 → 主模型也标记 error，附带 dep_id 信息
            await self._model_store.update_download_error(
                model_id, f"dependency {dep.dep_id} failed: {e}"
            )
            return  # 中止，不继续下载后续 dep

    # 5. 全部完成 → 主模型标记 done
    await self._model_store.update_download_done(model_id, resolved_path)
```

**dep 下载目录**：dep 通过 `snapshot_download(repo_id, local_dir=None)` 下载，由 HF hub 管理到 `HF_HOME/hub/`（与主模型的 `MODEL_CACHE_DIR` 独立）。`resolved_path` 记录 `snapshot_download` 的返回值（实际 snapshot 路径）。

**重试语义**：dep 下载失败后，主模型 `download_status='error'`。用户通过 Admin 界面"重试"操作（现有 retryDownload 流程）触发重新下载，此时已完成的 dep（status='done'）会被跳过。

### 6.3 torch.hub → HF 统一

TRELLIS2 `DinoV2FeatureExtractor` 将 `torch.hub.load(...)` 替换为 `Dinov2Model.from_pretrained(dep_paths["dinov2-vitl14"])`。

**⚠️ B2 实现前必做 Spike**：`torch.hub` 风格的 DINOv2 返回的是原生 `torch.nn.Module`，特征提取使用 `is_training=True` 获取 `x_prenorm`；HF `Dinov2Model` 的输出结构不同（`last_hidden_state`、`pooler_output`）。**必须在相同输入下对比两种方式的输出 tensor shape 和数值**，确认等价性后方可提交，否则推理质量静默下降。

`facebook/dinov2-large` 对应 `dinov2_vitl14` 架构，等价性在论文和社区已有验证，但接口层的调用方式需要适配。

---

## 七、构建运行时的变更

```python
# api/server.py: build_model_runtime()

# 改后：
model_path = resolved_path or model_path
dep_paths = await _resolve_dep_paths(model_id, dep_store)
# dep_paths: {"birefnet": "/data/hf/hub/...", "dinov2-vitl14": "/data/hf/hub/..."}

# ⚠️ 不在主进程设置 HF_HUB_OFFLINE（会破坏 WeightManager 的后续下载）
# 离线兜底在 worker 子进程内设置（见 7.1）

provider = build_provider(provider_name, model_path, dep_paths)
workers = build_gpu_workers(provider_name, model_path, dep_paths, ...)
```

### 7.1 WorkerProcessConfig 扩展（ProcessGPUWorker 子进程获取 dep_paths）

现有 `WorkerProcessConfig` 通过 `mp.Queue` 跨进程传递（pickle），需扩展 `dep_paths` 字段：

```python
@dataclass
class WorkerProcessConfig:
    provider_name: str
    model_path: str
    dep_paths: dict[str, str]  # 新增字段，pickle 安全
```

**离线兜底在子进程内设置**：`_build_process_provider` 内（而非主进程）设置环境变量，确保不影响主进程的 WeightManager 下载：

```python
def _build_process_provider(config: WorkerProcessConfig):
    # 子进程启动时设置离线标志，使任何未被 dep_paths 覆盖的 from_pretrained 快速失败
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return Provider.from_pretrained(config.model_path, config.dep_paths)
```

mock 模式下 `AsyncGPUWorker` 直接接受 provider 实例，dep_paths 在主进程 `build_model_runtime` 时已注入，无需额外处理（mock 模式通常在测试环境，离线标志可选）。

---

## 八、Admin UI 变更

### 8.1 模型详情对话框（已有）扩展

在只读详情里增加"依赖权重"区块：

```
依赖权重
  ─────────────────────────────────────
  BiRefNet           ZhengPeng7/BiRefNet
  /data/hf/hub/models--ZhengPeng7--BiRefNet/snapshots/...
  ● 已就绪

  DINOv2 ViT-L/14   facebook/dinov2-large
  /data/hf/hub/models--facebook--dinov2-large/snapshots/...
  ● 已就绪
```

### 8.2 Pending 下载区扩展

当前只显示主模型下载进度。扩展为分阶段显示：

```
正在下载 — TRELLIS2
  [主模型         ] ████████████ 100%  完成
  [DINOv2 ViT-L/14] ████░░░░░░░░  38%  1.1 MB/s
  [BiRefNet       ] 等待中
```

### 8.3 新增 API

- `GET /api/admin/deps` — 返回所有已缓存依赖的状态
- `GET /api/admin/models/{id}/deps` — 返回指定模型的依赖状态
- 已有 `GET /api/admin/models?include_pending=true` 扩展：pending 记录附带 `deps` 字段（B1 阶段需包含此字段，F1 依赖此数据）

---

## 九、现有部署迁移

当前部署机器上这些依赖已通过 HF cache / torch hub cache 存在。迁移步骤：

**顺序要求**：迁移脚本必须在所有 dep 标记为 done 后，才能切换 `build_model_runtime` 到新版本（含 `HF_HUB_OFFLINE=1` 和 dep_paths 注入）。新版本代码部署后，迁移脚本运行完成前不应重启 Load 服务。

1. 升级部署后，WeightManager 对现有模型（`download_status='done'`）运行一次扫描：
   对每个模型调用 `Provider.dependencies()`，尝试在本地 HF cache 中定位（`local_files_only=True`），找到则写入 `dep_cache.resolved_path = 已有路径`，并创建 `model_dep_requirements` 关联
2. torch.hub 缓存的 DINOv2（在 `~/.cache/torch/hub`）：用 `snapshot_download("facebook/dinov2-large", local_files_only=True)` 定位 HF 版本，如不存在则标记为 pending 并立即触发下载（不等到 Load 时）
3. 所有 dep 标记 done 后，迁移完成，此时启用新版 `build_model_runtime`
4. 迁移脚本设计为一次性，运行后删除

---

## 十、设计权衡说明

| 决策 | 选择 | 理由 |
|------|------|------|
| 依赖共享粒度 | 全局共享（dep_cache 独立表） | BiRefNet 被多 Provider 使用，避免重复下载 |
| torch.hub → HF | 统一替换（需 Spike 验证等价性） | 统一下载通道，dep_cache 统一管理，离线可控 |
| dep_paths 传递方式 | from_pretrained 新增参数 + WorkerProcessConfig 扩展 | 接口清晰，无全局状态污染 |
| 下载时机 | 添加模型时立即全部下载 | 避免 Load 时意外下载；用户在 Pending 区等待更直观 |
| 离线兜底 | Worker 子进程内设置 HF_HUB_OFFLINE=1 | 防止未被 dep_paths 覆盖的子模块静默联网；主进程不设置（避免破坏 WeightManager 下载） |
| 并发 dep 下载 | per-dep asyncio.Lock（WeightManager 进程级） | INSERT OR IGNORE 只防重建；Lock 防止多协程并发下载同一 dep，抢锁后二次检查 status |
| dep 失败处理 | dep error → 主模型 error，支持完整重试 | 状态清晰，用户可重试，已完成 dep 不重复下载 |
| 依赖版本锁定 | 当前不锁定 revision | v0.1 简化；dep_cache 表预留 revision TEXT 字段（DEFAULT NULL）供 v0.2 使用 |

---

## 十一、实现分阶段

| 阶段 | 内容 | 前置 |
|------|------|------|
| **B1** Backend: dep_cache + model_dep_requirements 表 + DepCacheStore + WeightManager 扩展 + API（含 pending deps 字段） | 无 |
| **B2** Backend: Provider.dependencies() 声明 + BaseModelProvider 改为 ABC + from_pretrained(dep_paths) + torch.hub 替换（需先做 DinoV2 等价性 Spike） | B1 |
| **B3** Backend: WorkerProcessConfig 扩展 + build_model_runtime dep_paths 注入 + HF_HUB_OFFLINE 兜底 + 现有部署迁移脚本 | B2 |
| **F1** Frontend: 模型详情扩展（依赖区块）+ Pending 区分阶段进度 + dep API | **B1**（F1 依赖 B1 的 dep 进度 API，与 B2/B3 并行） |

---

## 十二、Acceptance Criteria

### B1 验收

- [ ] `dep_cache` 和 `model_dep_requirements` 表在服务启动时自动创建（迁移兼容）
- [ ] 添加 TRELLIS2 模型：数据库中出现 `dinov2-vitl14` 和 `birefnet` 两条 dep_cache 记录，以及 2 条 model_dep_requirements 关联
- [ ] 添加 Step1X-3D 模型：`birefnet` dep_cache 记录已存在则不新建（共享），model_dep_requirements 创建 3 条关联
- [ ] `GET /api/admin/models?include_pending=true` 的 pending 记录包含 `deps` 字段（含 dep_id、status、progress）
- [ ] WeightManager 下载主模型成功 + 所有 dep 成功 → 主模型 `download_status='done'`
- [ ] WeightManager 下载主模型成功但某 dep 失败 → 主模型 `download_status='error'`，error 信息含 dep_id

### B2 验收（开工前：确认 pipeline.json / config.yaml 中各编码器路径字段的值）

- [ ] **B2 前置确认**：检查实际部署的 Step1X-3D 模型 repo 的 config.yaml，确认 `pretrained_dino_name_or_path`、`pretrained_t5_name_or_path`、`pretrained_clip_name_or_path` 是本地路径还是 HF repo ID；若为 HF ID，则追加对应 dep 声明
- [ ] **B2 前置确认**：检查 TRELLIS2 模型 repo 的 `pipeline.json`，确认 `args['image_cond_model']['name']` 是 DinoV2 还是 DinoV3
- [ ] 三个 Provider 均有 `dependencies()` classmethod（HunYuan3D 返回空列表）
- [ ] TRELLIS2 `from_pretrained` 接受 `dep_paths` 并使用本地路径加载 DinoV2 和 BiRefNet，无 torch.hub 调用
- [ ] Step1X-3D `from_pretrained` 接受 `dep_paths` 并将本地路径传给 SDXL pipeline，无 HF 远程调用
- [ ] Spike 产物：证明 DinoV2 两种调用方式输出张量 shape 相同、余弦相似度 > 0.99，以及端到端小样本 mesh 质量无肉眼可见退化

### B3 验收

- [ ] `WorkerProcessConfig` 含 `dep_paths: dict[str, str]` 字段
- [ ] `_build_process_provider` 在子进程内设置 `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`，主进程不设置
- [ ] ProcessGPUWorker spawn 后，`_build_process_provider` 使用 `process_config.dep_paths` 初始化 Provider
- [ ] **离线验证**：Load 完成后，Admin 界面继续添加新模型并触发下载，确认下载正常（主进程未被 OFFLINE 标志影响）
- [ ] **网络零外联验证**：Load 期间通过抓包或 `PYTHONPATH` 层 mock socket 确认子进程无外网请求
- [ ] 迁移脚本对现有部署干运行无报错，apply 后所有 dep 标记 done
- [ ] **并发验证**：同时添加 TRELLIS2 和 Step1X-3D，birefnet 只下载一次（dep_cache 中 birefnet 的 `download_progress` 单调递增，无抖动）

### F1 验收

- [ ] 模型详情对话框显示依赖区块（dep_id、hf_repo_id、local path、状态）
- [ ] Pending 区主模型 + 每个 dep 分阶段显示进度条
- [ ] dep 下载中时 pending 区轮询间隔 ≤ 2s
