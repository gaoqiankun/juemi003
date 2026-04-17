# VRAM Management — 完整设计

Date: 2026-04-17
Status: design

以本文为显存管理系统的设计基准。任何涉及显存管理的代码修改，须先对照本文。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────┐
│                  Model Scheduler                     │
│  （策略层：决定加载哪个模型，不决定驱逐时机）              │
└────────────────────┬────────────────────────────────┘
                     │ 触发加载请求
                     ▼
┌─────────────────────────────────────────────────────┐
│              Model Worker（每模型一个）               │
│  • 管理模型完整生命周期（加载→推理→卸载）               │
│  • 维护自己的 weight_vram_mb / inference_vram_mb 估算 │
│  • OOM 自愈：捕获→测量→更新估算→重新申请              │
│  • 响应 Allocator 的驱逐指令                          │
└───────────┬──────────────────────────┬──────────────┘
            │ 申请 / 归还              │ 驱逐指令（被动）
            ▼                          ▼
┌─────────────────────────────────────────────────────┐
│               VRAM Allocator                         │
│  • 账本：所有设备的 weight_bookings /                 │
│          inference_bookings / safety_margin 等        │
│  • 仲裁：申请不足时选候选驱逐，等待确认，更新账本        │
│  • 设备选择：request_weight 自选最优设备               │
│  • 迁移支持：request_inference 超时后在新卡预订资源     │
└─────────────────────────────────────────────────────┘
```

### 职责边界

| 实体 | 职责 | 不负责 |
|------|------|--------|
| **Model Scheduler** | 决定哪个模型应该被加载（策略） | 驱逐时机、设备选择 |
| **Model Worker** | 模型生命周期、自身 VRAM 估算、OOM 处理、物理迁移 | 判断是否有足够 VRAM |
| **VRAM Allocator** | 账本、准入仲裁、驱逐协调、设备选择 | 各模型需要多少 VRAM、物理加卸载 |

---

## 2. 接口定义

### VRAM Allocator 对外接口

```python
class VRAMAllocator:
    # ── async：可能需要等待驱逐或迁移 ─────────────────────────────
    async def request_weight(
        self, model_id: str, mb: int,
        exclude_device_ids: tuple[str, ...] = ()
    ) -> WeightAllocation:
        """
        申请权重显存。不传 device_id，Allocator 自选最优设备。
        async — 遍历设备：有空间直接 book；空间不足则驱逐 idle 模型；
        当前设备全 busy 则跳到下一设备。所有设备均无法满足时抛出异常。
        持 asyncio.Lock 跨越整个 check→evict→record 循环，防止并发驱逐。
        返回 WeightAllocation(allocation_id, device_id)。
        """

    async def request_inference(
        self, model_id: str, device_id: str, inference_mb: int, weight_mb: int
    ) -> InferenceAllocation:
        """
        申请推理显存。device_id 固定（模型已在该卡）。
        async — 尝试在当前设备驱逐 idle 模型腾空间；
        若当前设备全 busy，等待最多 5s（等 release_inference 信号）；
        5s 后仍不满足 → 在其他设备寻找能同时容纳 weight_mb + inference_mb
        的设备，预订该设备上的 weight + inference，
        返回 InferenceAllocation(inference_allocation_id,
                                  weight_allocation_id, device_id)。
        weight_allocation_id 非空表示需要迁移。
        """

    # ── sync：只改账本，无需等待 ───────────────────────────────────
    def release_weight(self, allocation_id: WeightAllocationID) -> None:
        """归还权重显存。sync — 更新账本。"""

    def release_inference(self, allocation_id: InferenceAllocationID) -> None:
        """归还推理显存。sync — finally 块保证必然执行，执行后通知等待者。"""

    def correct_weight(
        self, allocation_id: WeightAllocationID, actual_mb: int
    ) -> None:
        """
        加载完成后用实测值修正账本。sync — 只升不降：
        实测 > 预估时上调；实测 <= 预估时保持原值。
        """

    # ── 注册 ───────────────────────────────────────────────────────
    def register_worker(
        self, model_id: str, worker: "ModelWorkerInterface"
    ) -> None:
        """request_weight 成功后注册，供 Allocator 发驱逐指令时查找。"""

    def unregister_worker(self, model_id: str) -> None:
        """Worker 卸载后注销。"""
```

### Model Worker 对外接口（Allocator 调用）

```python
class ModelWorkerInterface(Protocol):
    async def evict(self) -> None:
        """
        Allocator 发出驱逐指令。
        async — Worker 须依次：
          1. 设置 _evicting = True，拒绝新推理请求
          2. 等待当前 in-flight 推理完成
          3. 停止 GPU 子进程
          4. 调用 allocator.release_weight(allocation_id)
          5. 调用 allocator.unregister_worker(model_id)
          6. 方法返回
        """
```

---

## 3. 核心流程

### 3.1 加载流程

```
触发来源（Scheduler / Admin / 启动预热）
  → Model Worker 启动
  → Worker 读取自身 weight_vram_mb 估算（DB 历史值，无则用默认值）
  → 调用 allocator.request_weight(model_id, weight_mb)
      → Allocator 持锁遍历设备：
        ┌─ 有设备空间足够 ──────────────────→ 记账，返回 WeightAllocation
        ├─ 有设备空间不足但有 idle 候选 ───→ 驱逐，记账，返回
        └─ 所有设备全 busy 无候选 ─────────→ 抛出 VRAMInsufficientError
  → Worker 收到 WeightAllocation(allocation_id, device_id)
  → Worker 向 Allocator 注册自己：register_worker(model_id, self)
  → Worker 启动 GPU 子进程（在 device_id 上）
  → 子进程 ready，报告实测 weight_reserved_mb
  → Worker 更新自身 weight_vram_mb 估算（只升不降）
  → Worker 调用 allocator.correct_weight(allocation_id, actual_mb)
  → Worker 设置 _weight_allocated = True
  → Worker 进入 idle，等待推理请求
```

### 3.2 卸载流程（被动驱逐）

```
Allocator 调用 Worker.evict()
  → Worker 设置 _evicting = True，拒绝新推理请求
  → Worker 等待当前 in-flight 推理完成
  → Worker 停止 GPU 子进程
  → Worker 调用 allocator.release_weight(allocation_id)
  → Worker 调用 allocator.unregister_worker(model_id)
  → evict() 返回
```

### 3.3 主动卸载（Admin 手动卸载）

```
POST /api/admin/models/{id}/unload
  → 找到该模型的 Worker
  → 调用 Worker.evict()（复用同一路径）
  注：主动卸载立即返回 202，evict() 在后台执行
```

### 3.4 推理流程（成功路径）

```
任务到达 Worker
  → Worker 设置 _inference_busy = True
  → Worker 读取自身 inference_vram_mb 估算
  → 调用 allocator.request_inference(model_id, device_id, inference_mb, weight_mb)
      → 当前设备有空间 → 记账，返回 InferenceAllocation(inference_alloc, None, device_id)
  → 收到 AllocationID，运行子进程 run_batch()
  → 成功：
      peak_mb = max_memory_allocated() - baseline_allocated
      Worker 更新自身 inference_vram_mb 估算（不允许向下 EMA）
      调用 torch.cuda.empty_cache()
      调用 allocator.release_inference(inference_alloc)
      Worker 设置 _inference_busy = False
```

### 3.5 推理流程（OOM 自愈路径）

```
run_batch() 抛出 OOM
  → Worker 捕获
  → 测量：bump_target = max(memory_reserved(), inference_mb_estimate * 1.5)
  → Worker 更新自身 inference_vram_mb 估算 = bump_target（直接替换）
  → 调用 torch.cuda.empty_cache()
  → 调用 allocator.release_inference(allocation_id)
  → 调用 allocator.request_inference(model_id, device_id, bump_target, weight_mb)
      → Allocator 可能驱逐其他 idle 模型
  → 收到新 AllocationID
  → 重试 run_batch() 一次
      成功 → 同 3.4 成功路径收尾
      OOM  → 任务失败，调用 release_inference，_inference_busy = False
```

### 3.6 推理流程（迁移路径）

```
allocator.request_inference() 在当前设备等待 5s 后仍无法满足
  → Allocator 在其他设备找满足 weight_mb + inference_mb 的设备 Y
  → Allocator 在 Y 上预订 weight + inference
  → 返回 InferenceAllocation(inference_alloc_y, weight_alloc_y, device_y)

Worker 发现 device_y != current_device，执行迁移：
  → 停止当前 GPU 子进程（物理卸载 A 卡）
  → 调用 allocator.release_weight(old_weight_alloc)   ← A 卡账本归还
  → 调用 allocator.unregister_worker(model_id)
  → 在 device_y 上启动新子进程（物理加载 B 卡）
  → 调用 allocator.register_worker(model_id, self)
  → 子进程 ready → correct_weight(weight_alloc_y, actual_mb)
  → 运行 run_batch()
  → 推理完成 → release_inference(inference_alloc_y)
  → Worker 设置 _inference_busy = False
```

---

## 4. VRAM 账本模型

```
safe_free(device) = total_vram
                  - driver_reserved      # 首个 Worker 上线时实测，per-device 静态值
                  - external_baseline    # 回路 3 后台任务维护
                  - weight_bookings      # 所有已加载模型权重之和
                  - inference_bookings   # 所有 in-flight 推理预留之和
                  - safety_margin        # 可配置，默认 1024 MB

准入条件：safe_free >= requested_mb
```

---

## 4.1 外部基线校准（回路 3）

**触发**：每 5s 执行一次，跳过条件：该设备有 in-flight 推理（`inference_bookings > 0`）。

**测量**：
```
expected_free = total_vram - driver_reserved - weight_bookings
probe_free    = nvmlDeviceGetMemoryInfo(device).free
external_obs  = max(0, expected_free - probe_free)
```

**更新规则（慢涨快降）**：
```
if external_obs <= 512 MB:           跳过（噪声）
elif external_obs > baseline:        baseline = 0.8*baseline + 0.2*external_obs
elif external_obs < baseline * 0.5:  baseline = 0.5*baseline + 0.5*external_obs
```

pynvml 不可用时：跳过，warn log 记录一次。

---

## 5. 并发控制

`request_weight` 和 `request_inference` 持 `asyncio.Lock` 跨越整个 `check → evict → record` 循环。

原因：若不持锁，A 在 `await evict()` 期间 B 进来看到同一个"不足"状态，选出另一个候选驱逐，造成不必要的双重驱逐。持锁确保每次只有一个请求在做决策，B 必须等 A 完整完成（驱逐+记账）后才能进入。

`release_weight` / `release_inference` 是 sync，在锁外执行（只改数字，不做决策）。

---

## 6. 驱逐候选选择规则

Allocator 触发驱逐时，候选条件：

1. **排除** `_weight_allocated == False`（还未完成加载的 Worker）
2. **排除** `_inference_busy == True`（推理进行中，含 OOM 重申请窗口）
3. **排除** `_evicting == True`（已在驱逐中）
4. **排除** 申请方自身
5. **优先** 同设备（先腾同卡空间）
6. **排序** LRU（最久未使用排前）

---

## 7. Worker 状态标志

```python
_weight_allocated: bool  # True = 已拿到 WeightAllocation，有实际显存占用
                         # False 时不可被驱逐候选选中
_inference_busy: bool    # True = 推理进行中（含 OOM 重申请窗口期）
                         # True 时不可被驱逐候选选中
_evicting: bool          # True = 正在响应驱逐指令，拒绝新推理请求
```

---

## 8. Model Worker 估算维护规则

### weight_vram_mb（只升不降）

```
actual = memory_reserved()    # 子进程 ready 后，首次推理前测量
if actual > stored:
    stored = actual
# actual <= stored：保持，宁高估不低估
```

### inference_vram_mb

成功路径（不允许向下 EMA）：
```
peak = max_memory_allocated() - baseline
new  = max(round(0.7*stored + 0.3*peak), peak)
```

OOM 路径（直接替换）：
```
new = max(memory_reserved(), stored * 1.5)
```

---

## 9. 代码映射（现状 → 目标）

| 现有组件 | 现有职责 | 目标变化 |
|----------|---------|---------|
| `engine/model_registry.py` | 管理加载状态 | 改为 Model Worker 容器 |
| `engine/model_scheduler.py` | 加载策略 + 驱逐决策 | 保留策略，移除驱逐决策 |
| `engine/vram_allocator.py` | 账本 + 推理侧准入 | 扩展：weight 申请/归还、设备选择、迁移支持 |
| `stages/gpu/stage.py` | 推理重试、跨卡迁移 | 简化：迁移逻辑移入 Worker |
| `stages/gpu/worker.py` | GPU 子进程 | 保留，成为 Worker 内部执行层 |
| `api/server.py` `_evict_idle_on_device` | 推理准入失败时驱逐 | 删除，逻辑移入 Allocator |

### 新增

| 组件 | 说明 |
|------|------|
| `engine/model_worker.py` | Model Worker：生命周期 + 估算 + OOM + 迁移 |
| `ModelWorkerInterface` | Allocator 调用 Worker 的接口（evict） |

---

## 10. 已知局限

- 推理中外部进程突增：唯一防线是 safety_margin + 回路 3 下次校准
- 推理估算永远无法精确：EMA 收敛到典型场景均值，极端 batch 仍可能超出
- 单 GPU 无处迁移：迁移失败后任务失败，正确行为
