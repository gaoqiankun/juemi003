# Caching Allocator 高水位逐次增长调查
Date: 2026-04-18
Status: done

## Goal

定位 inference lease 重构(commit `01029b3`)上线后,每次任务结束 caching allocator
高水位 +1 GB 不归还 CUDA 的根因。**只调查不修**,产出嫌疑清单,由 Orchestrator
决定如何验证 / 修复。

## 现场数据

生产 2 次连续推理(任务 `341dd95f` → `a141b6a7`),admin 面板与 nvidia-smi 一致:

| 任务 N 后 | nvidia-smi | external (probe 刷新后) |
|---|---|---|
| 1 | 17.3 GB | 1.0 GB |
| 2 | 18.5 GB | 2.2 GB |

净增 +1.2 GB。两次都增长,无反例。lease 修复同时上线,是高度相关的变量。

## 关键背景

- 本次 lease 修复让 inference allocation 持有窗口从「~30s gpu」延长到
  「gpu + export ~90s」(实测 export 耗时 50-62s)
- commit `e8ac251` 处理过 IPC mesh tensor 残留;`54542a4` 处理过 baseline 重置
- ModelWorker 跑在子进程(GPUWorkerHandle),主进程 `empty_cache` 只清主进程
- mesh `.cpu()` 转换发生在 export stage(SIGBUS 约束:不在 `_run_single` 同步转)

## Acceptance Criteria

- [ ] Worker 产出 `.ai/tmp/report-vram-leak-investigation.md`
- [ ] 列出 lease 退出前后所有可能持有 GPU 引用的对象(file:line + 引用链)
- [ ] 对比 commit `01029b3` vs `d903d56` 在 lease 窗口内引入的差异
- [ ] 确认 commit `e8ac251` / `54542a4` 已处理路径有没有被新代码绕过
- [ ] 给出 top 3 最可疑根因,每条带验证方法(读哪个对象 / 加什么 print)
- [ ] 报告里明确"开放问题"(代码读不出来、需运行时验证的)

## 调查范围

- `engine/pipeline.py`:`_run_gpu_export_with_lease` / `_run_gpu_with_oom_retry`
  lease 退出前后的引用清单
- `engine/model_worker.py`:`run_batch` / `apply_successful_inference_measurement`
  / `empty_cuda_cache` / `_run_batch`,主子进程清理边界
- `stages/gpu/worker.py`(GPUWorkerHandle IPC tensor 路径)
- `stages/export/stage.py`(mesh 交付 + .cpu() 时机)
- `model/trellis2/provider.py`:`run_batch` / `export_glb` / `_run_single`
- `git show 01029b3 d903d56 e8ac251 54542a4` 对比

## Out of Scope

- 不写修复代码
- 不跑测试 / 不重启服务
- 不假设结论 —— 嫌疑列出来,验证由 Orchestrator 决定
- ModelWorker 之外的 weight allocation 路径(本次不动)
- 前端面板(后端账本对了前端自然对)

## Output Spec

`.ai/tmp/report-vram-leak-investigation.md`:

```
## Suspect references
- file:line | 对象 | 为什么可能未释放(谁持有 / 何时本应清)

## Code path delta (01029b3 vs d903d56)
- 本次 commit 在 lease 窗口内引入或保留的新引用

## Already-handled paths (e8ac251 / 54542a4)
- 这两个 commit 已经清理的引用 + 新 lease 路径有没有破坏它们

## Most likely root cause (top 3)
- 位置 + 1 句假设 + 验证方法

## Open questions
- 代码读不出、需运行时验证的部分
```

## Notes

- 数据点只有 2 个,不足以说"线性增长 vs 封顶"。但「2/2 都增」已足以触发调查
- 调查产出后,可能的下一步:开 fix plan / 加 instrumentation 跑 5 次再判 /
  根据 top 1 嫌疑直接派修复 —— 由用户拍

## Summary

调查完成:commit `01029b3` 是 bookkeeping refactor,未引入新 CUDA tensor
引用。VRAM 增长是**预存在稳态被 lease 时序暴露** —— probe 在 export 期间
suspended,lease 退出后才观察到残留(allocator cache + IPC pinning)。

Top 3 嫌疑:
1. `stages/gpu/worker.py:200-214` `_pump_responses` 的 `message` 局部变量
   在 `queue.Empty` 分支不重绑,保留上一任务 mesh IPC 到下个任务首条响应到达
2. 子进程 `empty_cache` 在 `response_queue.put` 之后立刻跑,但此时 IPC
   还没被主进程消费,释放不到位
3. OOM 重试路径下子进程 allocator 碎片化(仅在近极限 VRAM 场景触发)

用户决策:**同时修 top 1 + top 2**,但因临时优先级(Hunyuan3D 卡 0% →
TaskStore locked 根因)插队,fix 留到后续。下一个 plan 开启时继续。
