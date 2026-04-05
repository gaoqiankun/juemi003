# Add Model Wizard (Step-by-step)
Date: 2026-04-06
Status: approved

## Goal

将 AddModelDialog 改为步骤式引导流程，明确告知用户每步在做什么、dep 从哪里来、下载什么。

## 设计

### 步骤

**Step 1 — 选择模型类型**
- 三张 provider 卡片（TRELLIS2 / HunYuan3D-2 / Step1X-3D）
- 每张卡片显示：名称、一句话描述、VRAM 需求（前端硬编码）
- 点击卡片选中，Next 继续

**Step 2 — 配置主模型权重**
- Display name（预填 provider 默认名，可修改）
- WeightSourcePicker（预填 HuggingFace + 对应 HF repo ID）
- 说明文字："主模型权重将在添加后自动开始下载"

**Step 3 — 配置依赖权重**（仅有 dep 的 provider 显示此步）
- 每个 dep 一张卡片：显示 dep description、默认 HF repo ID
- 已有 ready/done 实例 → 默认选"复用已有"，显示实例名 + 状态徽章
- 无现有实例 → 默认"从 HF 下载"（预填 hf_repo_id），可展开切换来源
- 说明文字："以下依赖权重将随主模型一起自动下载"

**Step 4 — 确认下载**
- 摘要列表：
  - 主模型：provider 名 · 来源路径
  - 每个 dep：dep description · 来源（或"复用已有实例 [name]"）
- [开始下载] 按钮（调 onSubmit）

### 步骤跳过逻辑
- 无 dep 的 provider：Step 1 → Step 2 → Step 4（跳过 Step 3）
- Step 3 dep 全部复用现有实例：仍显示 Step 3（让用户确认），但标注"无需下载"

### 导航
- 顶部步骤指示器（圆点 or 数字）
- Back / Next 按钮；Step 4 的 Next 改为 [开始下载]
- 关闭时重置到 Step 1

## 文件变更

### 前端（纯 UI 改动，无后端改动）

**`web/src/components/add-model-dialog.tsx`**
- 重写为步骤式组件；保留所有现有状态逻辑和 `onSubmit` payload 格式不变
- Provider 元数据硬编码（description、VRAM、default model_path），替换现有 `PROVIDER_OPTIONS`
- Step 3 deps 数据仍通过 `fetchProviderDeps` 获取（现有逻辑保留）
- `WeightSourcePicker` 组件保留复用

**`web/src/i18n/zh-CN.json` + `en.json`**
- `models.addModel.steps.chooseProvider`、`configWeights`、`configureDeps`、`confirm`
- `models.addModel.providerCard.vram`（"需要 X GB 显存"）
- `models.addModel.step2.autoDownloadNote`
- `models.addModel.step3.autoDownloadNote`、`models.addModel.step3.reusingExisting`、`models.addModel.step3.noDownloadNeeded`
- `models.addModel.step4.title`、`models.addModel.step4.mainModel`、`models.addModel.step4.dep`、`models.addModel.step4.reusingExisting`
- `models.addModel.startDownload`

## Acceptance Criteria

- [ ] Step 1：三张 provider 卡片，点击选中，Next 可用
- [ ] Step 2：display name 预填，model path 预填（HF repo），WeightSourcePicker 可用
- [ ] Step 3（有 dep 时）：每个 dep 卡片展示 description + 默认来源；有现有实例时默认复用
- [ ] Step 3（无 dep 时）：跳过直接到 Step 4
- [ ] Step 4：摘要正确反映 Step 2-3 的配置
- [ ] 点击 [开始下载]：onSubmit payload 格式与原有一致，下载正常触发
- [ ] 关闭/取消：重置到 Step 1
- [ ] `npm run build` zero errors
- [ ] 中英文 i18n 完整

## Out of scope

- 磁盘空间预估（数据不可用）
- 后端改动
- AddModelDialog 以外的文件
