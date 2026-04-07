# GPU Device Management — Auto-Detect + Admin Toggle
Date: 2026-04-06
Status: approved

## Goal

1. 启动时自动探测所有可用 CUDA 设备，无需配置 `GPU_DEVICE_IDS`
2. Admin 面板可在线启用/禁用单张卡，无需重启
3. 禁用状态持久化到 settings 表，重启后恢复

## 设计

### 1. 自动探测（`config.py` + `api/server.py`）

`config.py`：`gpu_device_ids` 默认改为 `()` 空 tuple（哨兵值，表示"未指定"）。

`api/server.py`：新增辅助函数 `_resolve_device_ids(config) -> tuple[str, ...]`：
- `config.gpu_device_ids` 非空 → 直接用（用户显式指定，保留向后兼容）
- 空 → `torch.cuda.device_count()` 探测，返回 `("0", "1", ...)` 全部卡
- torch 不可用 → fallback `("0",)`

启动时调用一次，得到 `all_device_ids`，后续所有地方替换原来的 `config.gpu_device_ids`。

### 2. 运行时 enable/disable（`stages/gpu/scheduler.py`）

`GPUSlotScheduler` 新增：
```python
_disabled: set[str]   # 当前被禁用的 device_id
_parked: set[str]     # 被禁用但还没有被 release 的（已 acquire 的）
```

`release(device_id)` 修改：
- 若 `device_id in _disabled` → 加入 `_parked`，不回 `_available`
- 否则正常 `_available.put_nowait(device_id)`

新增方法：
```python
def disable(self, device_id: str) -> None:
    """禁用 slot。正在使用中的任务跑完后不再接新任务。"""
    self._disabled.add(device_id)
    # 若 slot 当前在 available 队列里（idle），从队列移出放入 parked
    # 用 drain-and-refill 方式：取出所有 available，跳过 disabled，重新入队
    items = []
    while not self._available.empty():
        try:
            items.append(self._available.get_nowait())
        except asyncio.QueueEmpty:
            break
    for item in items:
        if item in self._disabled:
            self._parked.add(item)
        else:
            self._available.put_nowait(item)

def enable(self, device_id: str) -> None:
    """恢复 slot。若处于 parked 状态，立即重新加入 available。"""
    self._disabled.discard(device_id)
    if device_id in self._parked:
        self._parked.discard(device_id)
        self._available.put_nowait(device_id)

def disabled_device_ids(self) -> frozenset[str]:
    return frozenset(self._disabled)
```

### 3. 策略传播

`api/server.py` 启动时：
- 创建共享 `disabled_devices: set[str]`（从 settings 读取初始值）
- `runtime_loader` 闭包捕获 `disabled_devices`，`build_model_runtime` 新增参数 `disabled_devices`，构建 `GPUSlotScheduler` 时初始化 `_disabled`
- `model_registry` 新增方法 `iter_schedulers() -> Iterable[GPUSlotScheduler]`（遍历所有 ready runtime 的 scheduler）

Admin 更新 disabled_devices 时：
1. 保存到 settings_store
2. 更新共享 `disabled_devices` set（in-place）
3. 对所有 active scheduler 调用 `disable()` / `enable()`

### 4. 存储（`storage/settings_store.py`）

新增常量：
```python
GPU_DISABLED_DEVICES_KEY = "gpu_disabled_devices"
```
存储格式：JSON 数组 `["1", "3"]`，缺失 = 全部启用。

### 5. API（`api/server.py`）

`GET /api/admin/settings` 响应新增字段：
```json
{
  "gpuDevices": [
    { "deviceId": "0", "enabled": true },
    { "deviceId": "1", "enabled": false }
  ]
}
```

`PATCH /api/admin/settings` 支持新字段：
```json
{ "gpuDisabledDevices": ["1"] }
```
接收后做上述"Admin 更新"三步操作。

### 6. 前端（`web/src/pages/settings-page.tsx`）

Settings 页新增 "GPU Devices" 区块：
- 列出所有探测到的卡（`gpuDevices` 数组）
- 每张卡一行：device ID、启用/禁用 toggle（`ToggleSwitch`）
- 与现有 max_loaded_models 风格一致，保存时一并提交

`web/src/lib/admin-api.ts`：`SettingsData` 类型新增 `gpuDevices` 字段。

`web/src/i18n/zh-CN.json` + `en.json`：
- `settings.gpuDevices.title`
- `settings.gpuDevices.description`
- `settings.gpuDevices.device`

## 文件变更清单

| 文件 | 改动 |
|------|------|
| `config.py` | `gpu_device_ids` 默认改为 `()` |
| `storage/settings_store.py` | 新增 `GPU_DISABLED_DEVICES_KEY` |
| `stages/gpu/scheduler.py` | `GPUSlotScheduler` 新增 disable/enable/parked 逻辑 |
| `engine/model_registry.py` | 新增 `iter_schedulers()` |
| `api/server.py` | `_resolve_device_ids()`、闭包注入、API 扩展 |
| `web/src/lib/admin-api.ts` | `SettingsData` 类型扩展 |
| `web/src/pages/settings-page.tsx` | GPU Devices 区块 |
| `web/src/i18n/zh-CN.json` + `en.json` | 新增 i18n key |

## Out of Scope

- `PipelineCoordinator.worker_count` 和 `AsyncGen3DEngine.parallel_slots` 动态调整（固定为探测到的总卡数，不影响 GPU 调度正确性）
- GPU 显存用量展示
- 设备健康检测

## Acceptance Criteria

- [ ] 单卡环境：不设 `GPU_DEVICE_IDS`，自动使用 device 0
- [ ] 多卡环境：不设 `GPU_DEVICE_IDS`，自动探测并使用所有卡
- [ ] 设置 `GPU_DEVICE_IDS=0,1` 时，仍按指定卡运行（向后兼容）
- [ ] Admin Settings → GPU Devices：正确显示探测到的所有卡
- [ ] 禁用某卡：当前运行中任务跑完后不再调度到该卡；新任务不分配到该卡
- [ ] 启用某卡：立即重新参与调度
- [ ] 重启后禁用状态恢复
- [ ] `npm run build` zero errors
- [ ] `python -m py_compile` 所有修改文件无语法错误
