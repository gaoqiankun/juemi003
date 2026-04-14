# VRAM 面板单位 GB 化 + weight/inference 自动测量回写
Date: 2026-04-13
Status: done

## Background

Phase 6 面板部署后用户反馈:

1. 显存显示用 MB 太啰嗦(24000 MB),应为 GB(24.0 GB)
2. `weight_vram_mb` / `inference_vram_mb` 两个字段目前是 `storage/model_store.py:22-50` 里硬编码的 seed 估计值(`16000/8000`、`18000/9000`),**从未校准过**。现在 admission control、LRU eviction、Phase 5 跨设备迁移都依赖这两个值,估计偏差会直接影响调度正确性

用户定的路线是 **"加载前测 + 加载后测,超阈值则修正"**:seed 值只作为首次加载前的参考,运行时用 NVML / torch 实测值回写 DB。

基础设施:
- `engine/vram_probe.py::probe_device_free_mb(device_id)` — NVML per-device free,已存在
- `torch.cuda.memory_allocated()` / `max_memory_allocated()` / `reset_peak_memory_stats()` — per-process,worker 子进程可用
- `ModelStore.update()` 的 `_UPDATABLE_FIELDS` 已含目标字段
- `ModelRegistry.add_model_loaded_listener` 已有 listener 模式可扩展
- `pynvml` 已作为依赖引入

## Goal

1. **前端**:VRAM 面板所有显存数值由 MB 切换为 GB(1 位小数,如 `16.0 GB`),格式化逻辑收敛到单一函数
2. **Weight 自动测量**:模型加载完成后,用实测 weight 占用对比 stored `weight_vram_mb`;若偏差超阈值,EMA 回写 `ModelStore`
3. **Inference 自动测量**:每次 `run_batch` 完成后,用实测 peak inference 占用对比 stored `inference_vram_mb`;若偏差超阈值,EMA 回写 `ModelStore`
4. 所有测量结果**无条件记日志**(`structlog`),便于事后排查

## Acceptance Criteria

### S1 — 前端单位 GB 化
- [ ] `web/src/components/admin/vram-panel.tsx` 中 `formatVramMb` 重命名为 `formatVramGb`,输出 `{X.X} GB`(1 位小数,`value / 1024`,最小 0)
- [ ] 所有 callsites 已替换(约 10 处);TypeScript 编译通过
- [ ] 面板实际渲染:cluster 总览行、per-device 卡片、holders 表 VRAM 列、external occupation tooltip 全部显示为 GB
- [ ] `cd web && npm run build` 零错误
- [ ] i18n label(zh/en)**不含**单位 literal,保持原样;单位由值字符串携带

### S2 — Weight 自动测量 + EMA 回写
- [ ] `engine/model_registry.py` 新增 `add_weight_measured_listener(callback)` 接口,callback 签名 `(model_name: str, device_id: str, measured_weight_mb: int) -> Awaitable[None] | None`
- [ ] `_load_runtime(model_name, entry)`:
  - 加载前调用 `probe_device_free_mb(device_id)` → `before_free`
  - 加载后(success 分支)再次 probe → `after_free`
  - `measured_weight_mb = max(0, before_free - after_free)`
  - 若 `before_free is None or after_free is None`:跳过测量,warn log `weight_measure.probe_unavailable`
  - 若 `measured_weight_mb <= 0`:跳过(可能 GPU 被别的进程释放了显存导致负差),warn log
  - 否则 emit `_notify_weight_measured(model_name, device_id, measured_weight_mb)`
- [ ] `api/server.py` 注册 weight measured listener:
  - 从 `ModelStore` 读取当前 `weight_vram_mb`(可能为 `None`,也可能等于 seed)
  - **阈值判定**:`should_update = stored is None or abs(measured - stored) > max(stored * 0.15, 1024)`
  - **EMA**:若 `stored is None`,`new_value = measured`;否则 `new_value = round(0.7 * stored + 0.3 * measured)`
  - 若 `should_update`:调用 `ModelStore.update(model_id, weight_vram_mb=new_value)`,info log `weight_measure.updated`
  - 否则 info log `weight_measure.stable`
- [ ] 跳过测量条件:`config.is_mock_provider=True` 时不测量(mock 权重是 1 MB,测量无意义)
- [ ] 跨设备方差告警(可选,soft fail):若同一 model 在不同 device 上测出的差值超过 20%,warn log `weight_measure.device_variance`,不阻塞流程
- [ ] 测试:`tests/test_model_registry.py` 新增用例,fake `probe_device_free_mb` 返回固定值序列,断言 listener 被调用、值正确;fake `ModelStore.update` 断言被调用参数符合 EMA 公式和阈值判定

### S3 — Inference 自动测量 + EMA 回写(最简稳路径)

**设计原则:最少的 IPC 改动,没有新消息类型,没有跨机制 cross-check。**

- [ ] `stages/gpu/worker.py` 的 `_worker_process_main` 子进程:
  - 启动时(provider 已 init 成功后,在发送 `ready` 之前):
    - `import torch`
    - `baseline_mb = int(torch.cuda.memory_allocated(device) / (1024 * 1024))`
    - 存为子进程**局部变量**(不上报父进程)
    - 若 torch 不可用或 device 无效,baseline 设为 `None`,后续不测量
  - 收到 `run_batch` 请求,在执行 `provider.run_batch()` 前后:
    - 前:`torch.cuda.reset_peak_memory_stats(device)`
    - 后:`peak_mb = int(torch.cuda.max_memory_allocated(device) / (1024 * 1024))`
    - `inference_peak_mb = max(0, peak_mb - baseline_mb)` (baseline=None 时置 None)
    - 塞进 result 消息:`{type: "result", request_id, results, inference_peak_mb: int | None}`
- [ ] `stages/gpu/worker.py::ProcessGPUWorker._pump_responses`:
  - 处理 `result` 消息时,若 `inference_peak_mb` 存在且非 None,调用 `measurement_callback(model_name, device_id, inference_peak_mb)`
  - 字段缺失 / None:skip,不 raise(向后兼容)
- [ ] `ProcessGPUWorker.__init__` 新增可选参数 `measurement_callback: Callable[[str, str, int], None] | None = None`;`model_name` 由构造时注入(从 provider config)
- [ ] `AsyncGPUWorker`(in-process,mock 路径)**不做任何改动**,不测量
- [ ] `api/helpers/runtime.py`(或 build_model_runtime 调用点)把 callback 注入 `ProcessGPUWorker`,callback 内部调用和 S2 共享的 `_update_vram_estimate` 纯函数(签名 `(model_id, field_name, measured_mb) -> None`),复用同一阈值+EMA 逻辑
- [ ] **不做 cross-check**:S3 的 torch baseline 不回传父进程,也不和 S2 的 NVML delta 对比。两者独立工作,各管各的字段(weight 走 NVML,inference 走 torch peak)
- [ ] 首次测量(`stored is None`)直接 replace,不走 EMA
- [ ] 所有测量事件 `structlog.info` 无条件记录,字段 `model_name`/`device_id`/`field=weight_vram_mb|inference_vram_mb`/`measured_mb`/`stored_mb`/`new_mb`/`action=update|stable`
- [ ] 测试:
  - 单元测试 `_update_vram_estimate` 纯函数(阈值、EMA、首次 replace、skip 条件)
  - `tests/test_process_gpu_worker_stop.py` 或新增 `test_process_gpu_worker_measurement.py`:fake torch + fake callback,断言 result 消息的 inference_peak_mb 字段正确透传、callback 被调用参数正确、缺字段时不 raise

### 整体
- [ ] `uv run python -m pytest tests -q` 全绿(baseline ≥ 163)
- [ ] `uv run ruff check .` 零新增问题
- [ ] `cd web && npm run build` 零错误
- [ ] 手动验证路径(deploy 机):
  1. 重启,第一次加载一个模型 → log 出现 `weight_measure.updated` 或 `weight_measure.stable`
  2. 跑一次生成 → log 出现 `inference_measure.*`
  3. 刷新 admin VRAM 面板,数值显示为 GB
  4. 数据库查 `model_definitions` 表,确认 `weight_vram_mb` / `inference_vram_mb` 和日志里的 new_mb 一致

## 阈值与策略(已定)

- **超阈值判定**:`abs(measured - stored) > max(stored * 0.15, 1024)` (15% 或 1024 MB 取大)
- **更新策略**:首次 `stored is None` → 直接 replace;后续 → `new = round(0.7 * stored + 0.3 * measured)`
- **粒度**:per-model 单值(不分 device);跨 device 方差只 log warn
- **skip 条件**:mock provider / probe 不可用 / 负差值 / 外部进程污染(加载期间 NVML 变化异常)

## Open Questions

1. **EMA vs max for inference peak** —— 已决定:保留 EMA。
   理由:3D 推理显存稳定,`max` 策略在外部进程临时占用时会把尖峰锁死,无法回落到正常值。
   实施按本 plan,不 revisit。

2. **负差值处理**:S2 的 `before - after` 如果为负(加载过程中外部进程释放了显存),策略是 skip + warn。S3 **不提供 cross-check**(已删)。实施中如果发现 skip 率高,再单独开 plan 考虑兜底。

3. **EMA 初始值冷启动**:新部署环境下 seed 值本身就偏差大,EMA 需要若干次加载才收敛到真值。当前策略:`stored is None` 才 replace,否则 EMA。
   可以在部署后根据实际收敛速度决定是否加速(比如"首次测量偏差 > 30% 时直接 replace")。本 plan 不做。

## Out of Scope(明确排除)

- ❌ Per-device 卡片布局重构(多卡扩展性)—— 用户延后
- ❌ Admin UI 手动编辑 weight/inference VRAM 字段入口 —— 自动测量覆盖后优先级下降,延后
- ❌ Per-(model, device) 二维粒度 —— schema 改动大,用户选 per-model 单值
- ❌ 跨设备方差告警的 UI 展示 —— 本 plan 只记 log
- ❌ 历史测量值的时间序列持久化 —— 只存当前值
- ❌ Seed 值的初始化修正(修改 `_SEED_MODELS` 硬编码)—— 自动测量取代 seed,不动 seed

## Impact

- `engine/model_registry.py` — 加载前后 NVML probe + 新增 listener 接口(~50 行)
- `stages/gpu/worker.py` — IPC 协议扩展,子进程 torch memory 追踪(~80 行)
- `api/server.py` 或 `api/helpers/runtime.py` — listener 注册 + 阈值/EMA 逻辑(~60 行)
- `web/src/components/admin/vram-panel.tsx` — MB → GB 单位切换(~15 行)
- 测试 — `tests/test_model_registry.py`、`tests/test_process_gpu_worker_stop.py`(或新增 `test_vram_auto_measure.py`)(~150 行)

## 风险

- **NVML delta 污染**:加载期间若有外部进程分配/释放显存,`before-after` 差值会失真。缓解:交叉 S3 的 torch baseline;且 `is_mock_provider` 时跳过;负值跳过
- **torch peak 跨 batch 污染**:必须每次 batch 前 reset_peak,否则 peak 是从上次 reset 至今的最大值。acceptance 已要求 reset
- **子进程 baseline 时机**:baseline 必须在 `provider.init` 完成后再读取,否则读到 0。子进程内部顺序:provider init → read baseline → 发 ready
- **IPC 向后兼容**:老 worker 代码没有 `inference_peak_mb` 字段;父进程要容忍缺失或 None,不 raise

## Dispatch Strategy

单 plan 三阶段可以切成一个 Worker session 串行执行:

- Worker 先做 S1(纯前端,最简单,可独立 verify)
- 再做 S2(主进程,相对独立)
- 最后做 S3(IPC 改动,最复杂,需要 cross-check S2)

Worker 执行完写 `.ai/tmp/report-vram-auto-measure.md`,Orchestrator 走 validate。

## Summary

S1/S2/S3 全部完成。前端 VRAM 面板切换为 GB 显示（1 位小数）；运行时 weight 自动测量通过
NVML before/after 差值 + EMA 回写 `weight_vram_mb`；inference 自动测量通过 torch peak
per-batch + EMA 回写 `inference_vram_mb`。585 行改动，224 tests pass，前端 build 零错误。

## Key Decisions

- **EMA 策略**：`new = round(0.7 * stored + 0.3 * measured)`，首次 `stored is None` 直接 replace
- **阈值**：`abs(measured - stored) > max(stored * 0.15, 1024 MB)`
- **weight 走 NVML delta**，**inference 走 torch `max_memory_allocated` peak**，两者独立
- `_capture_cuda_baseline_mb()` 在 `provider.init` 后、发送 `ready` 前读取 baseline（确保不读到 0）
- `pending_vram_measurement_tasks` 在 FastAPI lifespan shutdown 时 drain，防止异步写回丢失
- mock provider（`weight_measurement_enabled=False`）完全跳过测量，避免 1 MB 假数据污染

## Changes

- `web/src/components/admin/vram-panel.tsx` — `formatVramMb` → `formatVramGb`，MB÷1024，1 位小数
- `engine/model_registry.py` — `add_weight_measured_listener`、NVML before/after probe in `_load_runtime`
- `api/server.py` — `_update_vram_estimate` 纯函数、`_persist_vram_estimate_measurement`、weight/inference listener 注册、task drain
- `api/helpers/runtime.py` — `measurement_callback` 参数透传到 `build_gpu_workers`
- `stages/gpu/worker.py` — `_capture_cuda_baseline_mb`、per-batch `reset_peak`/`max_memory_allocated`、`inference_peak_mb` 字段、`_pump_responses` callback 调用
- `tests/test_model_registry.py` — NVML probe + listener + EMA 测试
- `tests/test_process_gpu_worker_measurement.py` — 新增，inference peak 透传 + callback 测试

## Notes

- 手动验证路径（deploy 机）尚未执行，需用户在部署后确认 log 和 DB 字段
- `measured_weight_device_id is not None` 在 `_load_runtime` 中被双重 guard（redundant），不影响正确性，可在后续 cleanup 中去掉
