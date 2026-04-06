# Weight Manager — Cache Reuse + HF tqdm get_lock Fix
Date: 2026-04-06
Status: approved

## Goal

`engine/weight_manager.py` 两个 bug 修复：
1. 主模型重复下载：添加已下载模型会无条件重新下载
2. HF 下载报错：`'type object _HFProgressTqdm has no attribute get_lock'`

## 变更细节

### Fix 1 — 缓存复用（`download_model`，~line 129-150）

在调用 `_download_main` 前，先检查本地缓存：
```python
target_dir = self._cache_dir / _cache_key(model_id)
if target_dir.is_dir() and _snapshot_has_model_weights(target_dir):
    resolved_path = str(target_dir.resolve())
else:
    resolved_path = await self._download_main(...)
```
这样只要磁盘上已有该 model_id 的权重目录，就直接复用，不删不重新下载。

`_prepare_target_dir` 本身不改动——deps 的 URL 下载仍需要临时目录逻辑。

### Fix 2 — get_lock classmethod（`_build_hf_progress_class`，~line 591-624）

在 `_HFProgressTqdm` 类内加：
```python
import threading
_lock = threading.RLock()

@classmethod
def get_lock(cls):
    return cls._lock

@classmethod
def set_lock(cls, lock):
    cls._lock = lock
```
`_lock` 作为类变量定义在类体内（非闭包外），`get_lock` / `set_lock` 是 tqdm 约定的接口。

## 文件范围

- `engine/weight_manager.py` — 仅上述两处改动
- 不改其他文件
- 不改测试（无相关测试）

## Acceptance Criteria

- [ ] 已下载过的主模型（model_id 对应目录存在且有权重文件）再次触发下载时直接跳过，不重新下载
- [ ] `snapshot_download` 使用 `tqdm_class=_HFProgressTqdm` 时不报 `get_lock` AttributeError
- [ ] 现有单测 `uv run pytest tests/ -x -q` 通过（若有相关测试）
- [ ] 语法无误（`python -c "import engine.weight_manager"`）
