# Weight Manager — 权重获取与模型推理分离
Date: 2026-03-29 / Status: done / Evaluator: APPROVE
Status: done

Task A1: ✅ done (2026-03-29)
Task A2: ✅ done (2026-03-29)
Task B:  ✅ done (2026-03-29)

## Goal

将权重获取（下载/缓存）与模型推理（加载/运行）完全分离：

- 新增 `WeightManager` 服务，统一管理三种权重来源（HuggingFace / URL / Local）
- Provider 只接受本地路径，移除内部的 `snapshot_download` / `hf_hub_download` 调用
- Admin 中添加模型 = 触发下载，下载完成才进主列表
- 为未来替换推理后端（ONNX、TRT 等）打好基础

## Architecture

```
Admin 添加模型
    ↓
WeightManager.download(model_id, source, path)
    HF:    snapshot_download → MODEL_CACHE_DIR/{model_id}/
    URL:   HTTP download + extract → MODEL_CACHE_DIR/{model_id}/
    Local: validate exists → resolved_path = original path
    ↓ 更新 DB: download_progress, download_status, resolved_path
    ↓ 完成后模型进主列表

Admin 点 Load
    ↓
build_model_runtime → 读 resolved_path（本地路径）
    ↓
Provider.from_pretrained(local_path)  ← 纯本地 I/O，无网络调用
```

## Phases

### Task A1 · Backend Core
文件范围：`config.py`, `storage/model_store.py`, `engine/weight_manager.py`（新）, `api/server.py`

**config.py**
- 新增 `MODEL_CACHE_DIR: Path`，alias `MODEL_CACHE_DIR`，默认 `/data/models`

**storage/model_store.py**
- `model_definitions` 表新增列（兼容旧数据，均有默认值）：
  - `weight_source TEXT NOT NULL DEFAULT 'huggingface'`（`'huggingface' | 'url' | 'local'`）
  - `download_status TEXT NOT NULL DEFAULT 'done'`（`'downloading' | 'done' | 'error'`）
  - `download_progress INTEGER NOT NULL DEFAULT 100`（0–100）
  - `download_speed_bps INTEGER NOT NULL DEFAULT 0`
  - `download_error TEXT`
  - `resolved_path TEXT`（本地缓存路径；local 来源 = model_path；HF/URL = WeightManager 写入）
- 旧记录迁移：`resolved_path` 留 NULL（由 WeightManager 补全），`download_status='done'`（已有模型视为就绪）
- 新增 store 方法：
  - `update_download_progress(model_id, progress, speed_bps)`
  - `update_download_done(model_id, resolved_path)`
  - `update_download_error(model_id, error_message)`
  - `list_models(include_pending=False)`（默认只返回 `download_status='done'`）

**engine/weight_manager.py**（新文件）
- `WeightManager(model_store, cache_dir)` 类
- `async download(model_id, weight_source, model_path)` — 主入口
  - `huggingface`：`snapshot_download(repo_id, local_dir=cache_dir/model_id)` + 进度回调
  - `url`：httpx 流式下载 → 按扩展名解压（.zip / .tar.gz）到 `cache_dir/model_id/` → 校验非空
  - `local`：`Path(model_path).exists()` 校验 → 直接写 `resolved_path = model_path` → done
- 进度：每秒调用 `model_store.update_download_progress`
- 完成/失败：调用 `update_download_done` / `update_download_error`
- 加入 `AppContainer`

**api/server.py**
- `build_model_runtime`：读 `resolved_path` 替代 `model_path`；若 `resolved_path` 为 NULL 报错（告知先下载）
- `POST /api/admin/models`：
  - 接收 `weightSource`（必填）、`modelPath`（必填）
  - Local：同步校验路径存在；HF / URL：创建 DB 记录后异步触发 `WeightManager.download`
  - 返回含新字段的模型记录
- `GET /api/admin/models`：新增 `?include_pending=true` query param（默认 false）
- `DELETE /api/admin/models/{id}`：若正在下载，先取消 download task，再删 DB 记录

**docker-compose.yml / .env.example**
- 新增 `MODEL_CACHE_DIR=/data/models`

### Task A2 · Provider Cleanup
文件范围：`model/trellis2/`, `model/hunyuan3d/`, `model/step1x3d/`, `stages/gpu/worker.py`

**目标**：Provider 只接受已存在的本地路径，移除所有网络下载回退逻辑。

各 provider 的 `_resolve_model_path`（或等价逻辑）简化为：
```python
path = Path(model_path).expanduser().resolve()
if not path.exists():
    raise ModelProviderConfigurationError(
        f"weights not found at {path}. Use Admin to download first."
    )
return str(path)
```

需清理的具体调用：
- `model/trellis2/pipeline/pipelines/__init__.py`：`hf_hub_download(path, "pipeline.json")` 分支
- `model/hunyuan3d/pipeline/shape.py`：`snapshot_download(repo_id=...)` 回退
- `model/hunyuan3d/pipeline/texture.py`：`snapshot_download(repo_id=...)` 回退
- `model/step1x3d/pipeline/pipeline_utils.py`：`try_download` / `snapshot_download` 回退
- 三个 `provider.py` 的路径解析函数：移除 HF repo 检测分支，只保留本地路径分支

`stages/gpu/worker.py` 的 `_build_process_provider` 无需改动（model_path 语义已由 A1 保证为本地路径）。

依赖：A2 必须在 A1 完成后部署（A1 保证 resolved_path 为本地路径，A2 才能安全移除回退）；但可并行开发。

### Task B · Frontend
文件范围：`web/src/`

**Add Model 对话框**（新组件 `add-model-dialog.tsx`）
```
Display Name  [              ]   ID  [auto-slug, 可编辑]
Provider      [trellis2 ▼   ]   Min VRAM  [24000]

Weight Source
  ● HuggingFace  [tencent/Hunyuan3D-2      ] 示例文字提示
  ○ Local Path   [/data/models/my-model    ]
  ○ URL          [https://...model.tar.gz  ]

                              [Cancel]  [Add Model]
```
- 提交后关闭对话框，触发 pending 区刷新
- 校验：HF 格式 `owner/repo`，Local 不为空，URL 以 `http://` 或 `https://` 开头

**Models 页主列表**（`models-page.tsx`）
- 列表头部加 "+" 按钮，打开 Add Model 对话框
- 每行增加来源徽章（HF / Local / URL）
- `model_path` 列（缩略，tooltip 完整值）

**Pending 下载区**（`models-page.tsx` 底部，有 pending 时才渲染）
```
Downloading
  Hunyuan3D-2  tencent/Hunyuan3D-2
  ████████░░░  78%   12.3 GB / 15.8 GB   1.4 MB/s   [Cancel]

  My Custom Model  https://example.com/model.tar.gz
  ✗ Connection timeout                     [Retry] [Remove]
```
- 通过轮询 `GET /api/admin/models?include_pending=true` 实现（有 downloading 记录时每 2s 刷新）
- Retry：`POST /api/admin/models/{id}/retry-download`（或 DELETE + 重新 POST）
- Cancel / Remove：`DELETE /api/admin/models/{id}`

## Acceptance Criteria

### A1
- [ ] `POST /api/admin/models` 接受 `weightSource` 字段，Local 同步返回，HF/URL 异步下载
- [ ] 旧 DB 记录无损迁移（`download_status='done'`, `resolved_path=NULL` 暂留）
- [ ] `GET /api/admin/models` 默认只返回 done 模型，`?include_pending=true` 返回全部
- [ ] `build_model_runtime` 使用 `resolved_path`，本地路径不存在时报错提示明确
- [ ] `MODEL_CACHE_DIR` 环境变量生效，docker-compose / .env.example 已更新
- [ ] HF 下载进度（0–100）每秒写入 DB
- [ ] URL 下载：.zip 和 .tar.gz 均能解压，解压后目录非空
- [ ] 取消/删除正在下载的模型不报错，task 被正确 cancel

### A2
- [ ] 三个 provider 的 `from_pretrained(local_path)` 路径不存在时抛出明确错误
- [ ] `model/` 目录中不再有 `snapshot_download` / `hf_hub_download` 调用（`engine/weight_manager.py` 属设计意图，不在此 scope）
- [ ] 现有测试基线通过（`test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu` 为既有失败，正式豁免）

### B
- [ ] Add Model 对话框三种来源均可提交，表单校验覆盖错误格式
- [ ] HF / URL 提交后立即出现在 Pending 区，Local 提交后立即出现在主列表
- [ ] Pending 区进度条实时更新（2s 轮询）
- [ ] 下载完成后自动从 Pending 区移入主列表（无需刷新）
- [ ] Cancel / Retry / Remove 操作功能正常
- [ ] 来源徽章（HF / Local / URL）显示正确

## Key Decisions
- `resolved_path=NULL` 对旧记录：`build_model_runtime` 的回退策略——旧记录 NULL 时 fallback 到 `model_path`（保持向后兼容），后续可通过 WeightManager 补全
- URL 只支持 .zip / .tar.gz，单文件 URL 留 v0.2
- Local path 不复制到 MODEL_CACHE_DIR，用户自管

## Notes
- A1 和 A2 可并行开发，但 A2 的部署依赖 A1 完成
- B 依赖 A1 的 API 变更完成后开始
- 超标文件检查：`api/server.py` 已 2247 行，A1 改动后留意是否触发重构阈值
