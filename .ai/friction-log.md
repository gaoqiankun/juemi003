# 摩擦记录

> 遇到阻碍时随手记一行，不要求完整分析。定期（每 2 周或积累 10 条）回顾并决定是否优化工作流。
>
> **记录时机**：读了不需要的文件、大文件里找不到入口、找不到信息、流程断了需要额外询问、出现返工、token 明显浪费
> **同一问题出现 2 次**：升级处理——在 `impact-map.md` 或角色文件里补标注，而不只是继续记录
>
> **格式**：`[日期] [角色] 描述 | 估计成本`
> **成本标记**：🔴 高（多轮来回/大量重读）/ 🟡 中（多读了几个文件）/ 🟢 低（小困惑，一次解决）

---

<!-- 新条目加在这里，时间倒序 -->
[2026-04-12] [后端工程师] Phase 5 验证时 `uv run ruff check` 全仓输出 215 条历史错误（E402/C901/F401/nesting），增量 diff 是否引入新问题要在噪声里翻找；建议 ruff 增加 `--diff-from HEAD~1` 或 per-file 执行方式做增量门禁 | 🟡 中
[2026-04-12] [后端工程师] Phase 4c context 指定的 smoke 脚本路径 `/tmp/gpu_device_assignment_phase4c_smoke.py` 不存在，Worker 需要对照 context 里的 (a)-(e) 清单自行创建；建议 context 里要么附脚本内容要么标明 "Worker 自行创建 smoke 脚本" | 🟢 低
[2026-04-12] [后端工程师] `/tmp` 下的独立 smoke 脚本无法默认 import `gen3d` 包，需要手动加 `PYTHONPATH=..` 或 `PYTHONPATH=/data/home/gqk/work/hey3d` 才能正常运行；建议后续 smoke 脚本统一放 `scripts/smoke/` 或 context 里提醒 `PYTHONPATH` 约定 | 🟢 低
[2026-04-12] [后端工程师] 只读检索命令在默认沙箱内触发 `bwrap: loopback ... Operation not permitted`，需要切到提权模式才能继续常规文件读取/搜索 | 🟢 低
[2026-04-11] [后端工程师] Phase 1 初版把 mock 模式也纳入真实显存预算，导致无 GPU/小显存测试环境加载失败；需补充“mock 模式按 1MB 权重占位”分支才能通过现有行为预期 | 🟢 低
[2026-03-30] [后端工程师] 用户给的是工作区根路径 `.ai/tmp/prompt-b3.md`，实际文件在 `gen3d/.ai/tmp/`，先全局检索后才能继续 | 🟢 低
[2026-03-30] [后端工程师] 基线命令 `.venv/bin/python -m pytest` 与 `uv run python -m pytest` 初始都因 `.venv` 未安装 pytest/ruff 失败，需额外安装依赖后才能验收 | 🟡 中
[2026-03-25] [架构师] 并行下发时未提前说明"每个 agent 会创建 plan 文件"，协调者看到陌生文件产生困惑 | 🟡 中
[2026-03-25] [前端工程师] `npm` 默认使用 Node v14 导致 lint/build 直接报错，需手动切到 nvm 的 Node v24 才能执行校验 | 🟢 低

- [2026-03-29] Tasks 页统计数据"进行中"一直显示 0，实际有运行中任务（存量 bug，待排查）
