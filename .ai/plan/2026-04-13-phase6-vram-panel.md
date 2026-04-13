# Phase 6 — Unified VRAM Panel (read-only monitor)
Date: 2026-04-13
Status: done

## Summary

SystemPage 新增只读统一 VRAM 监视器面板：后端新增 `GET /api/admin/gpu/state` 端点整合 allocator snapshot / runtime states / device info，返回 cluster + holders + per-device 三层数据；前端新增 `VramPanel` 组件（三层布局：总览条 / 持有者表 / per-device 分区块）3s 轮询并在 tab 不可见时暂停。覆盖 weight + inference 两类持有者、effective_free / external_occupation 外部占用可视化。

## Goal

在 SystemPage 增加一个**统一 VRAM 活动监视器**面板，把多张物理 GPU 卡作为一个资源池呈现（OS 内存管理器 / 活动监视器 风格），让运维一眼看到：

- 集群 VRAM 水位总览（total / weight 已用 / inference 已用 / free）
- 哪些**持有者**（权重模型 + 活跃推理任务）在占用显存，各占多少 MB，落在哪张卡上
- 每张物理卡的分区明细（booked_free vs effective_free、外部占用标记、LRU 顺序、推理并发计数）

**本 plan 严格只读**——没有任何修改状态的按钮（卸载/驱逐/迁移都不做）。

## Non-goals（明确 out of scope）

- 任何写操作（手动卸载、触发 evict、强制迁移、调 budget）——这些是后续独立 plan
- GPU 利用率%、温度、功耗、风扇——需要额外的 NVML 字段采集，不在 allocator 现有数据范围内
- Prometheus 时序图（acquire wait p50/p99、evict 成功率趋势）——需要前端接 Prom 或后端聚合，留到 Phase 7
- 跨节点集群视图（多机）——当前架构单机单进程，无意义
- SSE/WebSocket 推送——3s 轮询足够，避免新增连接管理复杂度

## Design

### 后端

**新增端点** `GET /api/admin/gpu/state`（`require_admin_token`）

返回形状：
```json
{
  "cluster": {
    "deviceCount": 4,
    "totalVramMb": 97280,
    "reservedVramMb": 4096,
    "usedWeightVramMb": 32000,
    "usedInferenceVramMb": 2400,
    "freeVramMb": 58780,
    "effectiveFreeVramMb": 56200
  },
  "holders": [
    {
      "kind": "weight",
      "modelName": "trellis2",
      "deviceId": "0",
      "vramMb": 12000,
      "runtimeState": "ready"
    },
    {
      "kind": "inference",
      "allocationId": "infer-17",
      "modelName": "trellis2",
      "deviceId": "0",
      "vramMb": 600
    }
  ],
  "devices": [
    {
      "deviceId": "0",
      "name": "NVIDIA L40",
      "totalVramMb": 24320,
      "reservedVramMb": 1024,
      "usedWeightVramMb": 12000,
      "usedInferenceVramMb": 600,
      "freeVramMb": 10696,
      "effectiveFreeVramMb": 9200,
      "externalOccupationMb": 1496,
      "weightModels": [{"name": "trellis2", "vramMb": 12000}],
      "inferenceCount": 1,
      "enabled": true
    }
  ]
}
```

**数据来源整合**：
- `cluster` / `devices.*VramMb`：`VRAMAllocator.snapshot()` + `_get_gpu_device_info`（设备名）
- `externalOccupationMb`：`max(free_vram_mb - effective_free_vram_mb, 0)`（从 snapshot 派生）
- `holders.weight`：snapshot 的 `allocations` dict（已经是 `model_name → mb`）
- `holders.inference`：需要 **allocator.snapshot() 小幅增强** —— 当前只返回 `inference_allocations: dict(allocation_id → mb)`，补上 `inference_allocation_models: dict(allocation_id → model_name)`，避免 API 层访问 `_inference_to_model` 私有字段
- `runtimeState`：`model_registry.runtime_states()`
- `devices.enabled`：settings 里的 `gpu_disabled_devices` 取反

**`VRAMAllocator.snapshot()` 增强**（小改）：每个 device dict 增加 `"inference_allocation_models": dict(self._inference_to_model_on(device_id))` —— 或整体返回新字段 `inference_model_by_allocation_id`。倾向后者：全局字典一次返回，API 层自己 join。**具体字段名由 Worker 在实现时定，report 里写明即可。**

### 前端

**扩展 `web/src/pages/system-page.tsx`**：在现有 GPU 设备开关卡片**下方**插入一个新 Card —— `VramPanel`（提到 `web/src/components/admin/vram-panel.tsx`，因为 system-page 已 393 行，接近拆分阈值）。

**Card 内部布局**（三层）：

1. **顶部总览条**（~40 px）：
   - 水平堆叠条，4 段色：`reserved`（灰） / `weight`（蓝） / `inference`（橙） / `free`（透明带边框）
   - 右侧文本：`{usedWeight + usedInference} / {total - reserved} MB  (effective free {effectiveFree} MB)`
   - `external_occupation = free - effective_free > 0` 时右上角显示小红点 + tooltip

2. **持有者表**（主体）：
   - 列：`Holder` / `Type` / `Device` / `VRAM (MB)`
   - Type badge：`weight` / `inference` 两种颜色
   - Holder 名：weight 用 model name + runtime state badge；inference 用 `{modelName} · {allocationId}`
   - 按 `vramMb` 降序
   - 空状态：`No VRAM allocations`

3. **per-device 分区块**（底部网格，每卡一个小 Card）：
   - 顶部：设备名 + `device {id}` + enabled/disabled pill
   - 小型堆叠条（reserved/weight/inference/free/external_occupation）
   - 数字行：`total / used_weight / used_inference / free / effective_free`
   - `weightModels` 列表（chip 形式）
   - `inferenceCount` 数字

**API 调用**：`admin-api.ts` 新增 `getGpuState(): Promise<GpuStateResponse>`；`GpuStateResponse` 类型放在 admin-api.ts 顶部和其它 admin 类型并列。

**刷新策略**：
- 挂载立即拉一次
- 之后 `setInterval` 每 3s 拉一次
- 使用 `document.visibilityState === "visible"` 判断，tab 不可见时暂停
- `useEffect` cleanup 清 interval

**i18n keys**（`src/i18n/en.json` + `src/i18n/zh-CN.json` 双语必须同步）：
- `system.vramPanel.title`
- `system.vramPanel.cluster.total` / `usedWeight` / `usedInference` / `free` / `effectiveFree` / `externalOccupation`
- `system.vramPanel.holders.columnHolder` / `columnType` / `columnDevice` / `columnVram`
- `system.vramPanel.holders.typeWeight` / `typeInference`
- `system.vramPanel.holders.empty`
- `system.vramPanel.device.enabled` / `disabled`
- `system.vramPanel.externalOccupation.tooltip`

**布局规则遵守**：card `p-4` / `gap-3` / `rounded-2xl`，button `size="sm"`，不引入新 `sm:` / `md:` 前缀，per-device 网格用 flex wrap 而非 `grid-cols-2 md:grid-cols-4`。

### Mock 兼容性

`create_app` 在 mock 模式下 `vram_allocator` 也被初始化（以 `_detect_device_total_vram_mb` 回退到 `_DEFAULT_DEVICE_TOTAL_VRAM_MB`），所以 mock 模式下端点也能返回合理数据（reserved/weight/inference 全 0，free = total）。前端在 mock env 下能直接渲染，无需 mock fixture。

## Acceptance Criteria

### 后端
- [ ] `VRAMAllocator.snapshot()` 增强返回 allocation_id → model_name 映射（新字段，向后兼容）
- [ ] 新增 unit test `test_vram_allocator_snapshot_includes_inference_models`：reserve + reserve_inference 后断言 snapshot 含映射字段
- [ ] 新端点 `GET /api/admin/gpu/state`：需要 admin token，返回上述 JSON 形状
- [ ] 新端点 integration test（FastAPI TestClient，mock 模式）：
  - 无 token → 401/403
  - 有 admin token → 200，`cluster.deviceCount >= 1`，`devices` 数组非空，`holders` 数组存在（可以为空）
- [ ] `pytest tests -q` 全绿（baseline 216 passed，+2 新测试 ≈ 218）
- [ ] `ruff check .` 无新增告警

### 前端
- [ ] 新 component `web/src/components/admin/vram-panel.tsx`，独立文件 ≤ 300 行
- [ ] `system-page.tsx` 在现有 GPU 设备卡片下方挂载 `<VramPanel />`，新增代码 ≤ 40 行
- [ ] `admin-api.ts` 新增 `getGpuState` + 类型定义
- [ ] i18n 双语 keys 完整同步（en/zh-CN 键集相同）
- [ ] 3s 轮询 + visibility 暂停
- [ ] `cd web && npm run build` zero error
- [ ] 手动 smoke（mock 后端 + 前端 dev）：顶部总览条、持有者表（空态）、per-device 块都能渲染

### 交付形态
- [ ] 单 commit：`feat: Phase 6 — unified VRAM monitor panel`
- [ ] commit 包含 plan 文件（status: done）

## Files to touch

**后端（Python）：**
- `engine/vram_allocator.py` — `snapshot()` 增强（+~5 行）
- `api/server.py` — 新增 `/api/admin/gpu/state` 路由（~60 行），会让 server.py 从 ~3230 行再涨一点——**注意**：AGENTS.md 说 `api/server.py ~1900 lines, 新路由需 architect approval`。实际已 3230 行，远超指导值；但项目继续在加新 admin 路由（参考 hf-status / storage/stats 都挂在这里）。本 plan 按现状继续挂到 server.py，不做拆分，但 Worker report 里必须显式标注。
- `tests/test_vram_allocator.py` — 新增 1 个 test case
- `tests/test_admin_gpu_state.py` 或合并到现有 admin test —— 新 integration test

**前端（TypeScript/React）：**
- `web/src/components/admin/vram-panel.tsx`（新，独立文件）
- `web/src/pages/system-page.tsx` — 挂载 panel + import
- `web/src/lib/admin-api.ts` — `getGpuState` + 类型
- `web/src/i18n/en.json` + `web/src/i18n/zh-CN.json` — 新 key 集

## Key Decisions

1. **为什么新建 `/api/admin/gpu/state` 而不是改造 `/api/admin/dashboard`**：dashboard 当前 gpu 字段全占位 0 且没有前端消费者，改造它需要动单卡→多卡形状，反而引入兼容性债；独立端点语义清晰，未来 Phase 7+ 挂其它 GPU 观察视图也有落点
2. **为什么落在 SystemPage 而不是独立 Dashboard 页**：SystemPage 已经是 GPU 设备设置归属地（开关 + total memory），VRAM 明细是其自然延伸；新开 Dashboard 页会让 admin 导航更散，且需要决定 admin index 重定向目标
3. **为什么只读**：Phase 6 原定位是"显存明细展示"；写操作（卸载、evict、迁移）涉及并发安全、权限边界、审计日志等跨层设计，强塞进来会把 plan 撑到失控。留到后续独立 plan
4. **为什么 snapshot 增强而不是 API 层访问私有字段**：allocator 的内部映射是实现细节，API 层直接读 `_inference_to_model` 会让重构心智负担变大；snapshot 本就是 allocator 对外的观察契约点，正是该加字段的地方
5. **为什么 3s 轮询而不是 SSE**：简单可控，对齐 models-page 既有节奏；SSE 要新增连接管理、认证续期、reconnect 等基础设施，和"只读监视"目标不匹配

## Notes

- 当前 `api/server.py` 超出 AGENTS.md 指导大小（3230 >> 500 建议拆分阈值）——本 plan 继续往里加但 Worker 要在 report 里显式标注，未来 server.py 拆分是独立技术债
- Worker 必须先读 allocator.snapshot() 现有返回结构（`engine/vram_allocator.py:361-374`）和 `DeviceBudget` 定义（`:26-48`），字段命名风格对齐
- Worker 必须确认：mock 模式下 `vram_allocator` 是否真的会被初始化且 snapshot 可调——如果不会，需在 test 里 setup

## Changes

**后端：**
- `engine/vram_allocator.py` (+7) — `snapshot()` 每个 device 增加 `inference_allocation_models` 字段（allocation_id → model_name）；用 walrus + `is not None` 过滤避免 release 竞态
- `api/server.py` (+118) — 新增 `GET /api/admin/gpu/state`（require admin token）；整合 `vram_allocator.snapshot()` + `model_registry.runtime_states()` + `_get_gpu_device_info` + `disabled_devices`；返回 cluster/holders/devices 三层数据；`externalOccupationMb = max(free - effective_free, 0)`
- `tests/test_vram_allocator.py` (+23) — 新 test case `test_vram_allocator_snapshot_includes_inference_models`
- `tests/test_api.py` (+35) — 新 integration test `test_admin_gpu_state_requires_admin_token_and_returns_snapshot`

**前端：**
- `web/src/components/admin/vram-panel.tsx`（新建，268 行）— 三层布局组件 + 3s 轮询 + visibility 暂停 + cleanup；5 段堆叠条（reserved/weight/inference/external/free）
- `web/src/pages/system-page.tsx` (+5) — import + `<section><VramPanel /></section>` 挂载在 GPU 设备卡片下方
- `web/src/lib/admin-api.ts` (+46) — `GpuStateResponse` / `GpuStateCluster` / `GpuStateHolder` / `GpuStateDevice` / `GpuStateWeightModel` 类型 + `getGpuState()`
- `web/src/i18n/en.json` / `web/src/i18n/zh-CN.json` (+29 each) — `system.vramPanel.*` 17 个键，en/zh 集合严格一致

## Key Decisions

1. **独立端点而非改造 `/api/admin/dashboard`**：dashboard 的 gpu 字段全占位 0 且无前端消费者，改造需动单卡→多卡形状，反而引入兼容性债；独立端点语义清晰，Phase 7+ 其它 GPU 观察视图可挂同一 namespace
2. **snapshot() 增强而非 API 层读私有字段**：API 直接读 `_inference_to_model` 会让 allocator 重构心智负担变大；snapshot 本就是对外观察契约点，这是正确的扩展位
3. **字段语义对齐**：holders 区分 `kind: "weight" | "inference"`，weight 带 `runtimeState`，inference 带 `allocationId` + `modelName`（从 snapshot 新增字段 join）；deviceId 保持字符串与 allocator 内部一致
4. **前端 3s 轮询 + visibility 暂停而非 SSE**：对齐 models-page 既有节奏，避免新增连接管理/认证续期/reconnect 等基础设施，匹配"只读监视"目标
5. **Card 内部用 flex wrap 而非 grid-cols-2 md:grid-cols-4**：遵守 AGENTS.md "新代码不得引入 sm:/md: 前缀"约束
6. **`min-w-[260px]` arbitrary value**：per-device 卡最小宽度用 Tailwind arbitrary，不是 responsive prefix，合规

## Validate 结果

- 后端：`pytest tests -q` 218 passed（baseline 216 + 2 新），`ruff` 受触及文件 26 errors before/after 一致（无新增）
- 前端：`npm run build` zero error，i18n en/zh key 集 diff=0，组件 268 ≤ 300，system-page 挂载 +5 ≤ 40
- Code review Layer 2: CLEAN（2 个非阻塞 polish 点记录在 friction-log：`device.inferenceCount` 复用 cluster label 语义不精确；`Loading...` 硬编码未 i18n）

## Known Tech Debt

- `api/server.py` 从 3230 → 3348 行，AGENTS.md 要求拆分但本 plan 按 plan 预授权继续挂，未来独立 plan 处理
- Worker 未自产 `.ai/tmp/report-*.md` 的完整 decisions/friction surface——本次由 Orchestrator validate 时补录
