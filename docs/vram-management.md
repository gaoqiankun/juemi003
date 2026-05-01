# 显存管理架构

> 面向:想理解 Cubie 3D 生成服务怎么分配和回收 GPU 显存的工程师。
>
> 本文是**架构说明**,偏叙述和取舍。精确接口与流程规格见
> [`.ai/vram-management-design.md`](../.ai/vram-management-design.md)。

---

## 1. 为什么显存需要管理

Cubie 要在同一张或几张 GPU 上同时运行多个 3D 生成模型(Trellis2、HunYuan3D、
Step1X-3D),每个模型的权重都是 GB 量级,推理过程还会短暂产生峰值占用。

如果不做管理,会出现三种常见故障:

- **上线就 OOM**: 两个模型权重加起来超过单卡显存,第二个模型 `from_pretrained`
  直接失败
- **推理时 OOM**: 权重装下了,但推理峰值(sparse attention、大 batch、高分辨率)
  突然多要几 GB,CUDA runtime 抛异常
- **前后任务互相踩**: A 任务刚结束,B 任务立刻进来,但 A 的 CUDA tensor 还没
  真正被回收,B 以为有空间,实际 OOM

核心矛盾:**"够不够用"不是一个静态属性**,它依赖于当前加载哪些模型、有几个
推理正在跑、外部进程(比如用户在同机器上跑其他 CUDA 程序)占了多少。

所以需要一个账本 + 一套仲裁规则。账本叫 **VRAM Allocator**,仲裁发生在每次
"申请" 和 "归还" 时。

---

## 2. 三实体架构

Cubie 把显存管理拆成三个独立角色,各管一件事:

```
┌──────────────────────────────────────────────────────────────────┐
│                       Model Scheduler                             │
│  策略层。回答"现在应该加载哪些模型"。                                │
│  不回答:哪块卡、什么时候驱逐、够不够用。                             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 触发加载请求
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Model Worker(每模型一个)                       │
│  生命周期层。回答"某个模型的加载 / 卸载 / 运行"。                     │
│  维护自身的 weight_vram_mb / inference_vram_mb 估算(基于历史测量)。  │
│  不回答:够不够用、在哪张卡、能不能驱逐别人。                          │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ weight 申请/归还,驱逐响应
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                         VRAM Allocator                            │
│  账本层。回答"这张卡现在占了多少、还能放多少、要不要驱逐。              │
│  持有 per-device budget(weight bookings、inference bookings、       │
│  safety margin、external baseline),仲裁所有申请。                  │
│  不回答:模型有多大、往哪张卡放哪个模型。                              │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                              │ reserve / release(via lease)
                              │
┌──────────────────────────────────────────────────────────────────┐
│            Pipeline / Task Coordinator(任务协调层)                 │
│  任务级资源的拥有者。持有 InferenceLease,覆盖 gpu + export 两个     │
│  GPU-bound stage。处理 OOM 重试与 lease 异常释放。                   │
│  不回答:模型怎么加载、account 怎么记。                               │
└──────────────────────────────────────────────────────────────────┘
```

### 为什么要拆成三件事

早期(2026-03 之前)这些职责混在一个类里,出现过几次典型事故:

- **策略与机制耦合**: scheduler 既决定加载哪个模型,又执行驱逐,把 OOM
  事故的修复变成改策略文件——不同问题应该改不同地方
- **账本和执行耦合**: allocator 既记账又知道怎么 unload subprocess,
  测试时没法单独验证账本正确性
- **竞态窗口**: 加载和驱逐在同一把锁后面,但中间有 `await` 点,并发
  请求看到的"不足"状态可能属于不同时刻,导致双重驱逐

拆开后每个角色是 "纯函数式" 的边界:输入是明确的请求,输出是明确的响应,
中间没有跨层的隐藏状态。

---

## 3. 两种显存:Weight 与 Inference

显存占用有两种性质完全不同的来源:

| | 权重显存 (Weight) | 推理显存 (Inference) |
|---|---|---|
| **生命周期** | 模型加载后驻留,直到卸载 | 单次任务开始到结束 |
| **大小** | 模型静态属性(~16 GB / Trellis2) | 动态、依赖输入(~5 GB) |
| **可预测性** | 加载后测一次就固定 | EMA 估算 + OOM 自愈修正 |
| **拥有者** | Model Worker | **Pipeline 协调层(via Lease)** |
| **申请者** | Model Worker 自己 | Pipeline 代替 Worker 申请 |

Allocator 账本分别跟踪这两类,加起来加上 safety margin 和 external baseline
才是真正"这张卡可用多少显存"。

### 为什么 Inference 归 Pipeline、Weight 归 Worker?

这是 **2026-04-18 修订的核心决策**。旧实现里两者都由 Worker 管,直到
生产观测到一个显存记账 bug 才意识到 inference 的本质是任务级资源。

下一节展开这个决策。

---

## 4. 核心决策:Inference Allocation 是任务级资源

### 问题现场

2026-04-18 在生产观测:一个 Trellis2 任务跑完 GPU 推理(~79s),进入
导出阶段(~1s),admin 显存面板在这两步切换的瞬间发生诡异变化:

```
60% 生成中                          95% 生成中(export 阶段)
───────────────                   ─────────────────────
权重:    16.3 GB                    权重:    16.3 GB
推理:     5.5 GB   ←─ 账本对       推理:     0.0 GB   ←─ 账本显示归零
空闲:    25.6 GB                    空闲:    31.1 GB
有效空闲: 25.6 GB                   有效空闲: 27.1 GB  ←─ 还是有 4GB 差额
外部占用: 0                         外部占用: 4.0 GB  ←─ 凭空冒出
活跃推理: 1                         活跃推理: 0
```

后端日志显示 GPU stage 和 export stage 切换发生在 **400 微秒**之内:

```
09:36:25.071320  gpu stage.completed    (duration 79.37s)
09:36:25.071727  export stage.started
```

这 400μs 里不可能有任何真正的显存释放/再占用。"推理 0 + 外部 4 GB"是**记账
bug**,不是物理现象。

### 根因

旧实现的 allocation 生命周期:

```python
# engine/model_worker.py (旧)
async def run_inference(self, batch, options, progress_cb):
    allocation = await allocator.request_inference(...)   # ① 开账
    try:
        results = await self._run_batch(...)              # ② 跑推理
        return results                                    # ③ 返回 mesh
    finally:
        allocator.release_inference(allocation.id)        # ④ 关账 ← 问题
```

`_run_batch` 返回的 `GenerationResult.mesh` 是 **CUDA tensor**。它并没有在 ④
那一刻离开 GPU,而是被 export stage 接手,等到 export 调用 `.cpu()` 把 mesh
转到 CPU 内存,才真正释放显卡上的那段缓冲。

也就是说,**从 ④ 到 export `.cpu()` 完成之间,有一段 ~1s 的窗口**,CUDA
里实际占着 4 GB,但账本上已经写"推理 0"。差值被 dashboard 算法归为"外部占用"。

**本质**: allocation 的生命周期绑定在 "一次 `run_batch` 调用" 上,但 GPU
显存的真实占用期贯穿 "整个任务的 GPU-bound 部分"(gpu stage + export stage)。

### 解决思路的演化

最初的本能反应是在 `run_batch` 返回前把 mesh 转到 CPU,然后再释放 allocation。
但这条路**之前已经撞过 SIGBUS**(commit `c61a17a` 回滚):在 `response_queue.put()`
之前对 `MeshWithVoxel` 的 CUDA tensor 调 `.cpu()` 或 `setattr` 会触发 SIGBUS,
因为 torchsparse 内部持有这些 tensor 的原始指针,擅自搬动会让指针失效。
所以结论是:**不动 mesh 转换时机,改动 allocation 生命周期**。

第二个思路是把 `release_inference` 从 `run_inference` 的 finally 里延后到
"export 结束之后再释放"。但代码上怎么传?两种做法:

- **Worker 在完成后把 allocation 返回给调用方,由调用方在合适的时候释放** ——
  ModelWorker 的签名要变成返回 `(results, allocation)`,allocation 对象要被
  pipeline、gpu stage、export stage 几层透传。耦合扩散。
- **引入 Lease 对象,by-design 跨 stage 持有** —— 一个 context manager
  在 pipeline 层申请,包住 gpu + export 两个阶段,异常正常都自动释放。
  调用代码干净,ModelWorker 干脆不管 allocation 了。

第二种赢。

### InferenceLease 设计

```python
# engine/vram_allocator.py (新增)

class InferenceLease:
    """Per-task inference allocation holder.

    生命周期:
      - 进入 async-with 时 __aenter__ 获得 allocation
      - 正常或异常退出时 __aexit__ 保证 release
      - OOM 时 bump_and_retry_once 就地换更大的 allocation,
        不脱离 lease 对象
    """
    async def __aenter__(self) -> "InferenceLease": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    async def bump_and_retry_once(self, new_estimate_mb: int) -> None: ...


class VRAMAllocator:
    async def reserve_for_task(
        self, *, model_id: str, estimate_mb: int, weight_mb: int
    ) -> InferenceLease:
        """推荐入口。内部调 request_inference,把 allocation 包成 Lease。"""
```

Pipeline 层使用:

```python
estimate_mb = worker.estimate_inference_mb(sequence.options)
async with allocator.reserve_for_task(
    model_id=sequence.model,
    estimate_mb=estimate_mb,
    weight_mb=worker.weight_vram_mb,
) as lease:
    try:
        await gpu_stage.run(sequence)          # 推理,mesh 产生在 CUDA
    except OOMError:
        bump = worker.resolve_oom_bump_target_mb()
        await lease.bump_and_retry_once(bump)
        await gpu_stage.run(sequence)
    await export_stage.run(sequence)            # .cpu() 转换在这里
# lease 自动 release,此时 CUDA 已经真实回收
```

ModelWorker 相应瘦身——不再碰 allocation:

```python
class ModelWorker:
    # 保留
    async def load(self): ...                    # 权重生命周期
    async def unload(self): ...
    async def run_batch(self, ...): ...          # 纯执行,不申请 inference

    # 新增 / 公开
    def estimate_inference_mb(self, options) -> int: ...
    def resolve_oom_bump_target_mb(self) -> int: ...
    async def apply_successful_inference_measurement(self) -> None: ...

    # 删除
    # async def run_inference(...)   ← 原 OOM 重试 + allocation 管理都走了
```

---

## 5. 典型任务的显存时序

下图展示一个成功任务从开始到结束,各角色和显存账本的变化。

```
时间 →

Client      提交任务 ──────────────────────────────────────────→ SSE 订阅事件
              │
              ▼
Pipeline    preprocess ─→ [estimate] ─→ reserve_for_task ─→ GPU stage ─→ export ─→ complete
                           (worker)      │                   │           │
                                         │                   │           │
VRAM 账本 ─────────────┬─────────────────┴───────────────────┴───────────┴──────────────
weight      16.3 ────────────────────────────────────────────────────────────────→ 16.3
inference     0 ─────────────────────────→ 5.5 ─────── 5.5 ─────── 5.5 ─── 0 ────→ 0
external_occ  0 ─────────────────────────→   0 ───────   0 ───────   0 ─── 0 ────→ 0 ✓
                                         (lease 开始)                  (lease 释放)
                                                                        ↑
                                                                 mesh 已转 CPU,
                                                                 CUDA 真实回收

ModelWorker          load 完成,idle ──── run_batch ─── return mesh ──── idle ──→
                                        (内部只跑,不管账本)
```

关键约束:**lease 从 "GPU 计算开始前" 持到 "export 完成后",这期间账本的
`used_inference_vram_mb` 必定 > 0**。任何时间点刷 admin 面板都应该看到"推理
5.5 GB / 外部 0"。

OOM 变体见下一节。

---

## 6. OOM 自愈

推理显存估算不可能 100% 准确——模型在某些罕见输入下会比 EMA 估算多要 30%。
Cubie 的应对策略是 **一次性自愈重试**:

```
lease 块内 worker.run_batch() 抛 torch.cuda.OutOfMemoryError
  → Pipeline 捕获 OOM
  → worker.resolve_oom_bump_target_mb()
      返回 max(memory_reserved(), current_estimate * 1.5)
  → worker.update_inference_estimate(bump_target)
      持久化到 DB,下次不再低估
  → torch.cuda.empty_cache()
  → lease.bump_and_retry_once(bump_target)
      内部:allocator.release_inference(old) → request_inference(new)
      Allocator 可能在此刻驱逐其他 idle 模型
  → Pipeline 重试 worker.run_batch()
      成功 → 进入 export stage(正常路径)
      二次 OOM → 任务失败,lease __aexit__ 自动 release
```

设计上的关键点:

- **估算只升不降**: `update_inference_estimate` 不允许向下 EMA。否则会出现
  "一次极端输入 → 估算跳高 → 随后几个正常任务把估算 EMA 拉回低 → 再遇到那种
  输入又 OOM" 的死循环。
- **Bump 在 Lease 内完成**: 旧 allocation 的 release 和新 allocation 的
  request 都在同一个 lease 对象里。外部只看到"同一个 lease 从 A 切到 B",
  不会出现"旧 allocation 漏 release"的窗口。
- **一次机会**: 不做无限重试。如果 bump 后还 OOM,说明估算修正幅度不够,
  任务失败抛给上层,下一次 EMA 会进一步上调。

---

## 7. 跨卡迁移

当请求方所在的卡真的满了(既没空间也没能驱逐的 idle 模型),Allocator
会尝试把模型迁到另一张有空间的卡。

```
request_inference 在 device A 等待 5s 超时
  → Allocator 检查其他设备
  → 在 device B 上能同时容纳 weight + inference → 在 B 预订两份 allocation
  → 返回 InferenceAllocation 里 weight_allocation_id 非空 = 需要迁移

Lease 发现 allocation.weight_allocation_id 非空,触发 worker.migrate_to(B):
  → Worker 停 device A 上的 GPU 子进程,release_weight(旧)
  → Worker 在 device B 启新子进程,拿新的 weight allocation
  → Worker register_worker(model, self)
  → 子进程 ready → correct_weight(新 alloc, 实测值)
  → 迁移成功 → 返回,继续 run_batch
  → 迁移失败 → 抛错,lease __aexit__ 释放 inference,worker 自清 weight 状态
```

注意迁移的**物理执行**仍然在 Worker——它才知道怎么启停子进程。Pipeline
只负责触发信号。这保留了 Worker 对"模型生命周期"的单点所有权。

---

## 8. 外部占用与 Safety Margin

不是 Cubie 进程启动的其他进程也可能占卡(比如用户 ssh 上来跑 `nvidia-smi
dmon` 之外的 CUDA 程序)。账本看不到这些,但仲裁需要预防。

两条防线:

### Safety Margin(静态,1024 MB 默认)

每张卡固定扣掉一部分"可分配空间"。`safe_free = total - reserved - bookings
- margin`。margin 吸收小额外部波动和 CUDA 驱动的零散开销。

### External Baseline(动态,后台探针维护)

每 5s 启动一次背景任务:
1. **跳过条件**: 该卡当前有 in-flight 推理(`inference_bookings > 0`),
   因为推理本身会短暂爆高,会被误判成外部占用
2. **测量**: `external_observed = expected_free - nvml_probe_free`
3. **更新规则**(慢涨快降,避免对短暂峰值过度反应):
   ```
   external_observed > baseline → baseline = 0.8*base + 0.2*obs   # 慢涨
   external_observed < baseline * 0.5 → baseline = 0.5*base + 0.5*obs  # 快降
   ```
4. `expected_free - baseline = effective_free`,准入判断用 effective_free

两条防线加起来:短暂外部波动用 margin 吸收,持续性外部占用用 baseline 追踪。

---

## 9. 替代方案和为什么否决

### 方案 A:用 NVML 实时探针代替账本

每次分配前都读 NVML 查当前可用显存,不记账。

**否决理由**:
- 推理中 NVML 读数会剧烈波动,并发任务看到不同快照做不同决策,竞态严重
- 两次探针之间的空窗期任何人都能"偷跑",admission control 没意义
- 探针调用有 ~ms 级延迟,高频调用会拖慢申请路径

账本是**预订**(reservation),探针是**观测**(observation),两者不能相互替代。
Cubie 的做法是账本做准入,探针做背景修正(external baseline)。

### 方案 B:把 allocation 绑定到 GenerationResult 对象上

让 mesh 对象持有 allocation,`__del__` 时自动释放。

**否决理由**:
- Python `__del__` 时机不可控(GC 依赖引用计数 + 分代扫描),可能很晚才触发
- CUDA tensor 的生命周期通过 DataLoader、序列化、IPC 等路径容易多持有引用
- 把核心显存账本绑在易变的数据对象上,定位 bug 时没法 grep 到"谁还拿着"

Lease 是显式 context manager,生命周期一目了然,出错时堆栈告诉你在哪个 `async
with` 里漏了。

### 方案 C:延迟 release 但留在 ModelWorker 内

让 `ModelWorker.run_inference` 知道 "export 也会用我这个 mesh",延后 release
到 export 完成。

**否决理由**: ModelWorker 需要知道 export stage 的存在——反向耦合。下次
再加一个 post-processing stage 又得改 ModelWorker。

Lease 在 pipeline 层持有,新增 stage 只需要放进同一个 `async with` 块。

---

## 10. 已知局限

本架构明确**不**试图解决的问题:

- **推理中外部进程突增**: safety_margin 能挡住小波动,突增超过 margin 只能
  靠下次 external baseline 探针追上——中间会有一次 OOM 的可能
- **推理估算永远不精确**: EMA 收敛到典型分布,极端 batch size 或高分辨率仍
  可能超出。OOM 自愈是唯一兜底
- **单 GPU 无处迁移**: 迁移失败 = 任务失败。单卡部署接受这个行为
- **并发任务 peak 叠加**: `max_tasks_per_slot > 1` 时两个任务的推理峰值叠加
  超出 booking,Allocator 不知道,需要运营方保守配置

---

## 11. 代码结构速查

| 关注点 | 位置 |
|--------|------|
| 账本与准入 | `engine/vram_allocator.py` |
| 模型生命周期 | `engine/model_worker.py` |
| 加载策略 | `engine/model_scheduler.py` |
| 任务协调 + Lease 持有 | `engine/pipeline.py`(`PipelineCoordinator`) |
| GPU slot 调度 | `stages/gpu/scheduler.py` |
| GPU 子进程 | `stages/gpu/worker.py` |
| 推理执行 | `stages/gpu/stage.py` |
| 导出(`.cpu()` 转换 + GLB) | `stages/export/stage.py` |
| NVML 探针 | `engine/vram_probe.py` |
| Admin 面板 | `api/server.py:get_admin_gpu_state`(路由) + `web/src/components/admin/vram-panel.tsx`(渲染) |

---

## 12. 进一步阅读

- [`.ai/vram-management-design.md`](../.ai/vram-management-design.md) —— 精确接口
  签名、完整流程规格、边界条件、状态标志表。改代码前对照用
- [`.ai/decisions.md`](../.ai/decisions.md) —— 按时间倒序的决策日志,含每次
  行为变更的动机和影响范围
- [`.ai/plan/2026-04-18-inference-lease-lifecycle.md`](../.ai/plan/2026-04-18-inference-lease-lifecycle.md)
  —— Lease 重构的实施计划,含 task 拆分和 acceptance criteria

---

修订历史:

- **2026-04-18** — 初版。同步记录三实体架构(2026-04-17 确定)和 InferenceLease
  决策(2026-04-18 确定)。后者实施中。
