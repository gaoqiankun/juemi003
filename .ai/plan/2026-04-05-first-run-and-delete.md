# First-Run Wizard + Model Delete Button
Date: 2026-04-05
Status: approved

## Goal

1. 修正 seed：新安装时模型应为 pending 状态（需下载），而非假 done
2. 首次引导：无 fully-ready 模型且无下载中时，显示 wizard 引导用户下载默认模型
3. 模型列表加删除按钮：ready 模型支持删除；后端拒绝删除最后一个 fully-ready 模型
4. 升级用户：已有数据不受影响（seed 仅在 table 为空时插入，已有此保证）

## 定义

**Fully ready**：`download_status = 'done'` 且所有 dep 的 `download_status = 'done'`（与前端 `splitModels()` 一致）

## 设计决策

- 删除约束只在后端强制（返回 400），前端同步禁用按钮（当该模型是最后一个 fully-ready 时）
- 后端简化判定：`model_definitions` 中 `download_status = 'done'` 的记录数 ≤ 1 时拒绝删除最后一个（不联查 dep，实现简单且够用）
- Wizard 不做多步骤，inline 嵌入 models-page：替换空 state，显示默认模型卡片 + [开始下载] 按钮
- Wizard 触发条件：`models.length === 0 && pendingItems.length === 0`（无 ready 也无下载中）
- 若 `models.length === 0` 但 `pendingItems.length > 0`：正在下载中，wizard 不显示，保持现有 pending 进度卡片
- 默认模型信息从 API 返回的 `is_default = 1` 模型中读取（不硬编码前端）

## 文件变更

### 后端

**`storage/model_store.py`**
- `_SEED_MODELS` 中去掉隐式 `download_status='done'`（列默认值），改为在 INSERT 时显式传 `download_status='pending'`，`resolved_path=NULL`
- 同时在 INSERT 语句中补上 `weight_source`（现在 seed 没写，依赖列默认值 `'huggingface'` 可接受，但应显式）
- 新增 `count_ready_models() -> int`：`SELECT COUNT(*) FROM model_definitions WHERE download_status = 'done'`

**`api/server.py`**
- `delete_model`：删除前调用 `model_store.count_ready_models()`；若结果 ≤ 1 且当前 model `download_status = 'done'`，返回 400 `"cannot delete the last ready model"`

### 前端

**`web/src/pages/models-page.tsx`**
- Ready 模型行加 [Delete] 按钮；当 `models.length === 1`（该模型是最后一个 ready）时禁用
- 点击 [Delete] 弹确认对话框（复用现有 `Dialog` 组件），确认后调 `removeModel(id)`
- `models.length === 0 && pendingItems.length === 0` 时，替换 ready 区域为 `<FirstRunWizard>`

**`web/src/components/first-run-wizard.tsx`**（新文件）
- 从 `models` + `pendingItems` 拿不到默认模型时，调一次 `GET /api/admin/models` 取 `is_default=1` 的 pending 模型
- 实际上：wizard 在 models-page 里渲染，直接从 `pendingItems`（若有）或额外逻辑获取默认模型信息
- 更简单方案：models-page 已有 `models` 和 `pendingItems`，seed 后默认模型在 `pendingItems`（因为是 pending 状态）；但 wizard 触发条件是 `pendingItems.length === 0`，所以首次加载时 pendingItems 为空，需要显示 seed 的默认模型——这意味着要从 raw API response 拿 `is_default=1` 的记录

  **修正**：`splitModels()` 中 pending 模型进 `pendingItems`，wizard 从 `pendingItems` 里找 `is_default=true` 的显示；wizard 触发条件改为 `models.length === 0`（不管是否有 pending），pending 进度在 wizard 下方正常显示
  
  → **最终触发条件**：`models.length === 0`
  → Wizard 显示 seed 默认模型的信息（从 `pendingItems` 找 `isDefault=true`，找不到则显示通用提示）
  → 若 `pendingItems` 中已有默认模型在下载（`downloadStatus !== 'pending'`），wizard 改为显示下载进度而非 [开始下载]

**`web/src/i18n/zh-CN.json` + `en.json`**
- `models.firstRun.title`, `models.firstRun.description`, `models.firstRun.startDownload`, `models.firstRun.downloading`
- `models.list.delete`, `models.list.deleteConfirmTitle`, `models.list.deleteConfirmDescription`, `models.list.deleteConfirmOk`
- `models.list.deleteLastError`（删除最后一个 ready 模型时的错误提示）

## Acceptance Criteria

- [ ] 全新安装：DB 空时 seed 三个模型，TRELLIS2 为 `download_status='pending'`、`is_default=1`
- [ ] 升级安装：已有数据不变（seed 不执行）
- [ ] 首次进入 Admin Models：无 ready 模型时显示 wizard，显示 TRELLIS2 信息和 [开始下载] 按钮
- [ ] 点击 [开始下载]：调 `addModel` 触发下载，wizard 切换为进度显示
- [ ] 有 ready 模型时：不显示 wizard，正常显示模型表格
- [ ] Ready 模型行有 [Delete] 按钮；多个 ready 模型时可正常删除
- [ ] 只剩一个 ready 模型时：[Delete] 按钮禁用
- [ ] 后端 DELETE 最后一个 ready 模型：返回 400
- [ ] 中英文 i18n 完整

## Out of scope

- 添加模型页面（AddModelDialog）的完整重设计（单独 plan）
- Dep 的 fully-ready 联查（后端删除约束只检查主模型 download_status）
- Wizard 多步骤流程
