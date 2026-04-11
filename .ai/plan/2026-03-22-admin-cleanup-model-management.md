# Admin 全站清理 + 模型管理功能化
Date: 2026-03-22
Status: done

Date / Status: 2026-03-22 / done / Commits: N/A（按仓库 AGENTS 约束，本次未执行 git commit）
## Goal
- 清理 Admin 面板中 mock 时代遗留的装饰信息、假统计和冗余描述文案。
- 将模型页改造为可操作的管理列表（启用/禁用、设为默认、删除）。

## Key Decisions
- 清理优先于“填充感”：无真实数据支撑的 UI 区块直接移除，不保留占位描述。
- 模型管理仅保留当前 v0.1 必需操作，不新增“添加模型”入口。
- API 密钥页改成“真实数据 + 最小可用操作”：展示现有 key 列表、支持创建新 key，并一次性展示返回 token。

## Changes
- `web/src/components/layout/admin-shell.tsx`
  - 移除 sidebar 底部“环境 / 主部署”卡片。
- `web/src/pages/dashboard-page.tsx`
  - 统计卡片移除底部辅助描述文案；
  - “最近任务”区域移除与队列分层相关副标题文案；
  - 列表去掉无实际意义的主题/耗时展示，仅保留任务核心字段。
- `web/src/hooks/use-tasks-data.ts`
  - 任务数据结构改为真实字段映射（id/model/status/createdAt/latency/owner）；
  - 删除前端伪造日志与队列信息映射。
- `web/src/pages/tasks-page.tsx`
  - 顶部统计卡片移除统一占位描述；
  - 列表区去掉“优先队列/默认队列”相关标题描述；
  - 移除右侧“操作日志”卡片；
  - 表格去除 subject/queue/progress 等伪字段，仅保留真实任务信息。
- `web/src/hooks/use-models-data.ts`
  - 改为返回可操作模型列表与行为方法：`setModelEnabled`、`setModelDefault`、`removeModel`；
  - 操作完成后静默刷新模型状态。
- `web/src/pages/models-page.tsx`
  - 删除顶部假统计、卡片式展示及导入占位区；
  - 重做为紧凑管理表格：模型名、启用开关、默认标记/设为默认、删除；
  - 删除操作加入确认弹窗，所有操作接入后端 API。
- `web/src/hooks/use-api-keys-data.ts`
  - 改为真实 key 列表映射（id/label/createdAt/isActive）；
  - 新增 `createKey` 操作并支持刷新列表。
- `web/src/pages/api-keys-page.tsx`
  - 移除 fake usage 统计、scope tags、轮换/停用占位说明；
  - 保留并功能化“创建密钥”区域（名称输入 + 创建 + 一次性 token 展示）；
  - 顶部仅保留真实可计算指标“活跃密钥”。
- `web/src/pages/settings-page.tsx`
  - 移除区块二级描述大标题，仅保留区块标题；
  - 页面结构保持为纯配置表单。
- `web/src/lib/admin-api.ts`
  - 补充 admin models/admin keys 的原始响应类型与创建 key 方法声明，支撑页面真实数据流。
- `web/src/i18n/en.json`、`web/src/i18n/zh-CN.json`
  - 补齐模型管理列表与 API 密钥创建流程所需文案；
  - 清理 “priority/default queue” 等不准确文案；
  - 精简 settings 关键字段说明。

## Notes
- 验证结果：
  - `.venv/bin/python -m pytest tests -q` → `128 passed`
  - `cd web && npm run build`（Node v24.14.0）→ 通过，TypeScript 无错误
- 本轮未修改 engine 层、ModelStore/SettingsStore 存储层，以及用户侧 Generate/Gallery/Viewer/Setup 页面逻辑。
