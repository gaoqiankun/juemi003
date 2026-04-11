# GPU 显存分配器：多模型动态调度
Date: 2026-04-11
Status: phase-1-done

## Goal

设计 OS 级别的 GPU 显存分配回收机制。每个模型声明 `weight_vram`（权重常驻）和 `inference_vram`（推理临时占用），分配器统一管理所有 GPU 的显存预算，实现多模型共卡、并发推理、故障恢复。

## 分阶段实施

### Phase 1：基础分配器 + 加载调度（解决当前 bug）

**目标**：多模型可以加载到同一张卡，不再 CUDA 初始化失败。

**内容**：
- VRAMAllocator 核心：DeviceBudget 记账（total / reserved / allocations）
- 模型声明 weight_vram_mb / inference_vram_mb（provider 提供估算值）
- model_store schema 增加两个字段
- 加载时由 allocator 选卡（剩余显存 >= weight_vram），不再盲目占所有卡
- ModelRegistry.load() 接受指定 device_id
- build_model_runtime 只在分配的卡上创建 worker

**验收**：2 卡环境加载 2 个模型成功，各分配到合适的卡上。单卡可装多个模型（权重总和不超限）。

---

### Phase 2：推理准入控制

**目标**：推理前检查显存，够就跑，不够就排队。

**内容**：
- GPUSlotScheduler 推理前调 allocator 申请 inference_vram
- 推理完成后释放 inference_vram
- 显存不足时排队等待（同卡有其他推理在跑，等完成释放后继续）
- 支持并发推理：两个模型 inference_vram 之和放得下就同时跑

**验收**：同卡两模型，显存够时并发推理；不够时排队等待，不 OOM。

---

### Phase 3：同卡 evict

**目标**：推理时显存不够，主动卸载同卡空闲模型腾空间。

**内容**：
- 推理准入失败时，查找同卡上无推理任务的模型
- 卸载空闲模型释放 weight_vram
- 释放后重新检查显存，满足则执行推理
- evict 策略：LRU（最久未使用的优先卸载）

**验收**：模型 A 推理时显存不足，自动卸载同卡空闲模型 B，A 成功推理。

---

### Phase 4：实时校准 + 外部占用感知

**目标**：感知外部进程占用显存，不盲目 OOM。

**内容**：
- 关键决策前（加载、推理准入）查 `torch.cuda.mem_get_info()` 获取实际显存
- `effective_free = min(actual_free, booked_free)`，取较小值
- 检测 external_used = actual_used - our_booked_used
- 外部占用时等待，超时可配置（默认 30s，支持动态调整）

**验收**：外部进程占 10G 显存后，allocator 感知到并正确扣减可用额度，不 OOM。

---

### Phase 5：跨卡迁移

**目标**：当前卡不可用时，模型迁移到其他卡继续服务。

**内容**：
- 推理请求发现当前卡显存不足（外部占用 + 同卡 evict 后仍不够）
- 查找其他有足够空间的卡
- 在新卡上加载模型权重（启动新 worker）
- 请求挂起等待迁移完成，迁移成功后在新卡上执行推理
- 释放旧卡上的模型

**验收**：GPU 0 被外部占满，模型自动迁移到 GPU 1 执行推理，请求不报错。

---

### Phase 6：Admin UI 显存状态展示

**目标**：可视化显存分配状态。

**内容**：
- API 端点返回每张卡的显存明细：total / reserved / 各模型 weight + inference 占用 / external / free
- Admin UI GPU 页面展示分配状态（已有 GPU 设备列表，扩展信息）

**验收**：Admin 页面可查看每张卡的显存分配详情。

---

## 架构选择

保持多进程架构（每个模型 per device 一个子进程），主进程 VRAMAllocator 做中心化调度。

## 向后兼容

- `vram_gb` 保留，作为总量展示
- `estimate_vram_mb()` 保留，内部改为 weight + inference 之和
- 模型未声明新字段时 fallback：按 vram_gb 估算拆分

## Notes

- weight_vram_mb / inference_vram_mb 由 provider 在支持模型时估算确定
- 不支持单模型跨多卡（tensor parallelism）
- 迁移时请求挂起等待，不报错
- 外部占用等待超时支持动态调整
