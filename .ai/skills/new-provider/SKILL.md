# Skill: 接入新的 3D 生成 Provider

> 当需要添加一个新的 3D 生成模型（如 TripoSG、CraftsMan 等）时使用本 Skill。

## 前置理解

每个 Provider 必须实现 `model/base.py` 中的 `BaseModelProvider` Protocol：

```python
class BaseModelProvider(Protocol):
    @classmethod
    def from_pretrained(cls, model_path: str, **kwargs) -> "BaseModelProvider": ...
    def run_batch(self, images, options, progress_cb, cancel_flags) -> list[GenerationResult]: ...
    def export_glb(self, result: GenerationResult, output_path: str, options) -> None: ...
```

参考实现：`model/hunyuan3d/provider.py`（最完整）或 `model/trellis2/provider.py`。

## 步骤

### 1. 创建 Provider 目录和文件

```
model/<provider_name>/
├── __init__.py
└── provider.py       # Mock 和 Real 两个类
```

Mock 类命名：`Mock<Name>Provider`，用 `asyncio.sleep` 模拟延时，返回合法占位 mesh。
Real 类命名：`<Name>Provider`，调用真实模型推理。

### 2. 注册到工厂函数

在 `api/server.py` 的 `build_provider()` 工厂函数中添加 elif 分支：

```python
elif provider_type == "<provider_name>":
    if provider_mode == "mock":
        return Mock<Name>Provider()
    else:
        return <Name>Provider.from_pretrained(model_path)
```

### 3. 添加模型定义到数据库

在 `storage/model_store.py` 的 `_seed_default_models()` 或通过 Admin API 添加 model_definitions 记录。
关键字段：`provider_type`（对应工厂函数 key）、`vram_gb`（VRAM 估算值，影响调度上限）。

### 4. 补充 Docker 依赖

在 `docker/trellis2/Dockerfile` 中参考 HunYuan3D 依赖段落，添加新模型的 Python 依赖和 git clone 命令（若需要外部 repo）。

### 5. 编写测试

参考 `tests/test_api.py` 中 hunyuan3d 的 Mock Provider 测试块，新增：
- mock 模式下的 happy path 测试
- export_glb 正常执行测试

### 6. 验收

```bash
python -m pytest tests -q   # 不得少于 161 passed
```

Admin 面板 → Models 页 → 新增模型，选择新 provider_type，点击 Load，状态应变为 ready。

## 注意事项

- `progress_cb` 的 stage_name 必须是 `gpu_ss` / `gpu_shape` / `gpu_material` 之一（状态机硬编码）
- `GenerationResult.mesh` 是 provider 和 export stage 之间的唯一交接数据结构，类型必须与 `export_glb` 期望的一致
- Mock 实现必须在无 GPU 环境下可运行（用于 CI 和本地开发）
