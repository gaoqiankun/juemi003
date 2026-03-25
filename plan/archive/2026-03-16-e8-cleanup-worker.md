# E8 · DB 驱动的 Artifact 清理 Worker
Date / Status: 2026-03-16 / done / Commits: uncommitted

## Goal
将 artifact 清理从"per-delete asyncio task"改为"DB 驱动 + Event 激活的单一 worker"，
实现有界并发、持久可靠、重启自动恢复。

## Key Decisions

### DB 层
- `tasks` 表新增 `cleanup_done INTEGER DEFAULT 0`（0=待清理，1=已清理），启动时自动迁移
- 新增 `list_pending_cleanups(limit) -> list[task_id]`：查 `deleted_at IS NOT NULL AND cleanup_done = 0`
- 新增 `mark_cleanup_done(task_id)`：设置 `cleanup_done = 1`

### Worker 机制（async_engine.py）
- 引擎持有 `_cleanup_event: asyncio.Event` 和 `_cleanup_semaphore: asyncio.Semaphore(5)`
- 启动时：检查 DB 是否有待清理任务，有则 `event.set()`；启动 `_cleanup_worker` 协程
- Worker 循环：
  1. `await event.wait()`
  2. `event.clear()`
  3. 从 DB 批量取待清理 task_id（每批 20 条）
  4. 用 Semaphore 控制并发，并行清理 artifact
  5. 每条清理完后 `mark_cleanup_done(task_id)`，失败只记 warning
  6. 若还有待清理继续循环，否则回到等待
- 停止时：cancel worker task，等待退出

### delete_task 改动
- 移除 `_background_tasks` set 和 `_schedule_artifact_cleanup` / `_cleanup_artifacts`
- 软删除写 DB（`deleted_at`，`cleanup_done=0`）后调 `_cleanup_event.set()`，立即返回

## Changes
| 文件 | 变更说明 |
|------|---------|
| `storage/task_store.py` | `cleanup_done` 列迁移；`list_pending_cleanups`；`mark_cleanup_done` |
| `engine/async_engine.py` | 移除 `_background_tasks` 机制；新增 Event + Semaphore + worker 协程 |
| `tests/test_api.py` | 更新清理相关测试以适配新机制，补充重启恢复与迁移断言 |

## Notes
- Semaphore(5) 控制并发，防止大量删除时 I/O 风暴
- Worker 每批处理 20 条，防止单次处理量过大
- 重启后启动时检查 DB，确保历史遗留清理任务不丢失
- 外部行为（DELETE 返回 204、清理 best-effort）不变
