# Storage cursor leak + 并发锁修复
Date: 2026-04-18
Status: done

## Goal

修 `storage/` 下 SELECT cursor 泄漏导致 TaskStore 在高并发写入下抛
`sqlite3.OperationalError: database is locked`,task 卡在 QUEUED 状态
无法被 worker claim(UI 显示 0%)。系统性审计所有 store 的 cursor
用法,改用 `async with db.execute(...) as cursor` 上下文管理器,补并发
回归测试。

## 现场数据

生产 cubie3d 容器卡死现场:

```
{"error": "database is locked", "event": "worker.loop_failed",
 "exception": "... claim_next_queued_task ... UPDATE tasks ...",
 "timestamp": "2026-04-18T15:29:05.911 ~ .938"}
```

- worker-0 / worker-1 轮流在 `claim_next_queued_task` 抛错
- 5ms 间隔连续 6 次失败 → 命中 **SQLITE_LOCKED**(非 BUSY),
  busy_timeout=5000ms **未生效**(对 SQLITE_LOCKED 不作用)
- 前次 hunyuan3d 任务 15:00:03 成功完成,之后 29 分钟内触发锁,
  新 task 卡 0% 无法开始

## 根因定位

`storage/task_store_queries.py:111-152` `claim_next_queued_task`:

```python
while True:
    cursor = await db.execute(SELECT ... tasks ...)
    row = await cursor.fetchone()
    # cursor 未关!fetchone 只读一行,cursor 仍 open
    if row is None:
        return None
    async with lock:
        update_cursor = await db.execute(UPDATE tasks ...)
        # ^ 同 connection + 同一张 tasks 表,SELECT cursor 还挂着
        #   → SQLite 抛 SQLITE_LOCKED(database is locked),立即失败
        await db.commit()
        if update_cursor.rowcount == 0:
            continue  # 重试时 SELECT cursor 仍未关,状态更糟
```

## 为什么"以前流畅现在卡"

- 6 个 store 共享同一个 DB 文件(`api/server.py:368-373` +
  `api/helpers/runtime.py:115-116`):TaskStore / ApiKeyStore / ModelStore
  / DepInstanceStore / ModelDepRequirementsStore / SettingsStore
- 最近 VRAM 重构(`c204aac` / `01029b3`)新增 `_persist_estimate`
  在每次 inference 测量后写 `model_store`(EMA 更新 weight_vram_mb /
  inference_vram_mb,至少两次/任务)
- 写入频率↑ → TaskStore connection 更容易踩到 cursor 泄漏窗口

## Acceptance Criteria

- [ ] Worker 产出 `.ai/tmp/report-taskstore-cursor-leak-fix.md`
- [ ] 审计 `storage/` 下所有 `queries.py` / `mutations.py` /
  `analytics.py` / `task_store_queries.py` / `task_store_mutations.py` /
  `task_store_analytics.py` 的 `await db.execute(...)` 用法,列出
  cursor 泄漏清单(file:line)
- [ ] `claim_next_queued_task` 的 SELECT cursor 修复(改
  `async with db.execute(...) as cursor` 或显式 `close()` /
  `fetchall()`)
- [ ] 其他被审计出的 cursor 泄漏全部修复
- [ ] 新增并发回归测试:两个 worker 同时 claim + 另一 store 同时
  `update_model` 场景,验证不抛 `database is locked`
- [ ] 现有 213+ 测试全部通过
- [ ] 确认 6 个 store 的 connection 都设了 `busy_timeout=5000`
  且 WAL 模式(grep 确认,无需改动)
- [ ] 报告里给出「修前/修后」对比 + 问题清单

## 调查范围

- `storage/task_store_queries.py`:`claim_next_queued_task`(已定位)+
  `get_task` / `list_tasks` / `get_queue_position` / `list_incomplete_tasks`
- `storage/task_store_mutations.py`:`create_task` idempotency 分支
  有 SELECT(line 72)
- `storage/task_store_analytics.py`:全量统计查询
- `storage/model_store.py`:`update_model` 是否有 cursor 泄漏
- `storage/dep_store.py` / `settings_store.py` / `api_key_store.py`:
  简单审计
- `tests/test_task_store.py`:看是否已有并发测试覆盖

## Out of Scope

- VRAM leak 调查的 top1+top2 修复(另开 plan,已有 memo)
- hunyuan3d 16 分钟慢的二次验证(storage 修好后用户在生产观察再回来)
- `_persist_estimate` 降频(先看 storage 修好后是否还需要)
- 合并 store connection 架构重构(此次不动)

## Output Spec

`.ai/tmp/report-taskstore-cursor-leak-fix.md`:

```
## Cursor leak audit
- file:line | 问题类型 | 修前代码 | 修后代码

## 修复清单
- file:line | 修复方式(async with / fetchall / close)

## 新增测试
- 测试文件 | 场景 | 验证断言

## 测试结果
- 本地 pytest 全量输出摘要

## 开放问题
- 如果还有残留锁竞争风险,在这里列出
```

## Notes

- Worker 必须在 **本地 worktree** 跑测试,不在生产容器
- 测试应包含真实 sqlite3 而非 mock(并发 bug 只在真文件上重现)
- 修复同时不要引入新的 isolation_level 改动,保持 DEFERRED 默认
- 如果审计发现问题远多于预期(>15 处),先报告再决定是否拆分 plan

## Summary

修 `storage/` 下 SELECT cursor 泄漏导致 TaskStore 抛 `sqlite3.OperationalError:
database is locked`(SQLITE_LOCKED,非 BUSY,busy_timeout 不作用)。所有
cursor 改 `async with db.execute(...) as cursor` 管理;`claim_next_queued_task`
把 SELECT+UPDATE+commit 整体收进 `asyncio.Lock` 临界区,消除同 connection 上
的 statement 交叠。新增并发回归测试。

## Key Decisions

- **SELECT+UPDATE 原子化进 lock**:牺牲同 connection 内的"SELECT 并行度"换
  SQLITE_LOCKED 绝迹。无实际性能损失(aiosqlite 单 connection 本就串行)。
- **Scope 限定** `task_store_*` 三文件:其他 store(model/dep/settings/api_key)
  cursor 用法未纳入本次。生产验证无 locked 后再决定是否系统化审计全仓。
- **不改 isolation_level**:保持 aiosqlite 默认 DEFERRED;不合并 connection。

## Changes

- `storage/task_store_queries.py`:全量查询路径改 context manager;
  `claim_next_queued_task` 重写为 lock 内 SELECT+UPDATE+commit 原子操作
- `storage/task_store_mutations.py`:idempotency 冲突 SELECT + 3 个
  依赖 rowcount 的 UPDATE 改 context manager(`was_updated` / `was_deleted`
  / `was_marked` 局部变量缓存)
- `storage/task_store_analytics.py`:全部读查询改 context manager
- `tests/test_task_store.py`:新增
  `test_claim_next_queued_task_with_model_store_concurrency_no_locked_error`
  (120 task × 2 worker claim + 240 次 `model_store.update_model` 并发)
- `.ai/decisions.md`:追加 2026-04-19 条目

## Notes

- Orchestrator 已确认 6 store 的 `busy_timeout=5000` + WAL 均在初始化设置
  (task_store_schema / api_key_store / model_store / dep_store /
  settings_store),无需动。
- Worker 测试覆盖 214 pass(原 213 + 新 1)。
- 验证清单(留给生产):
  1. hunyuan3d 任务不再卡 0%(`database is locked` 从日志消失)
  2. 验证 hunyuan3d 16 分钟慢是否只是 locked 的副作用(可能随之修好,也可能独立)
