# E1 · ProcessGPUWorker 子进程崩溃检测
Date: 2026-03-15
Status: done
Commits: none

## Goal
子进程意外崩溃（CUDA OOM、segfault 等）时，`_pump_responses` 因 `queue.get()` 无 timeout 而永久挂起，导致所有 pending future 永远不被 resolve。需在进程死亡后尽快（秒级）失败所有 pending 请求，并让 pump 循环干净退出。

## Key Decisions
- 修改 `_pump_responses` 里的 `asyncio.to_thread(queue.get)` 改为 `queue.get(timeout=N)`，捕获 `queue.Empty` 后检查 `self._process.is_alive()`
- 进程死亡时：对所有 `self._pending` 中的 future 设置 `ModelProviderExecutionError`，对未完成的 `_startup_future` 同样报错，然后退出循环
- timeout 建议 1.0s，保证崩溃检测延迟 ≤ 2s，对生产影响可忽略
- 不引入额外 watchdog task，逻辑全部收在 `_pump_responses` 内，保持结构简单

## Changes
| 文件 | 变更说明 |
|------|---------|
| `stages/gpu/worker.py` | `_pump_responses` 改用 `queue.get(timeout=1.0)`，`queue.Empty` 后检查子进程存活；死亡时统一 fail `_startup_future` 和全部 pending future，并清空 `_pending` 后退出 |
| `tests/test_worker.py` | 新增子进程崩溃场景测试，验证 pending/startup future 收到 `ModelProviderExecutionError` 且 pump task 干净退出 |
| `tests/test_worker.py` | 新增 `stop()` 正常 shutdown 场景测试，验证发送 shutdown、等待 `stopped`、不触发 kill |

## Notes
- `_pending` 清空后 pump 退出，`run_batch` 的 caller 会收到异常，由 `GPUStage` 转为任务 failed
- 不需要自动重启 worker 进程（重启逻辑复杂，留 Phase D 考虑）
- `stop()` 走正常 shutdown 消息路径，不受影响
- `python -m pytest tests -q` 结果：`36 passed`
