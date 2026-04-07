# System Page — GPU Devices + Storage
Date: 2026-04-07
Status: approved

## Goal

将 Settings 页中的 GPU Devices 和 Storage 两个 section 拆分到独立的 System 页，
同时在 Storage 清理孤儿缓存前加确认 dialog。

## 变更清单

### 新建 `web/src/pages/system-page.tsx`

包含两个 section（从 settings-page.tsx 迁移，逻辑和样式保持一致）：

**GPU Devices section**（完整迁移）：
- 列出所有 GPU 设备（device label、name、totalMemoryGb、enable/disable toggle）
- 调用 `fetchSettings` + `updateSettings`（复用现有 API）
- toggle 变更后立即 PATCH（不需要保存按钮，和 settings 页不同——每个 toggle 独立即时生效）

**Storage section**（完整迁移 + 新增确认 dialog）：
- 磁盘使用进度条、cache/orphaned 统计（复用现有逻辑）
- 清理孤儿缓存按钮点击后弹出确认 dialog：
  - 标题：`storage.cleanOrphans.confirmTitle`
  - 描述：显示孤儿大小（`orphan_bytes`）和数量（`orphan_count`），告知不可恢复
  - 按钮：[取消] [确认删除]
  - 确认后执行清理，结果 toast.success

使用现有 `Dialog / DialogContent / DialogHeader / DialogTitle / DialogDescription` 组件。

### 修改 `web/src/pages/settings-page.tsx`

- 删除 GPU Devices section（含相关 state：`updateGpuDevice`）
- 删除 Storage section（含相关 state：`storageStats`、`isCleaning`、`refreshStorageStats`、`handleCleanOrphans`）
- 删除不再需要的 import（`getStorageStats`、`cleanOrphans`、`formatBytes`、`StorageStats` 等）

### 修改 `web/src/App.tsx`

```tsx
import { SystemPage } from "@/pages/system-page";
// ...
<Route path="system" element={<SystemPage />} />
```

### 修改 `web/src/components/layout/admin-shell.tsx`

导航数组新增（放在 settings 之前）：
```ts
{ key: "system", path: "/admin/system", icon: Server }
```
`Server` 从 `lucide-react` 引入。

### 修改 `web/src/i18n/zh-CN.json` + `en.json`

新增：
- `shell.nav.system`：`"系统"` / `"System"`
- `storage.cleanOrphans.confirmTitle`
- `storage.cleanOrphans.confirmDescription`（含 `{{count}}` 和 `{{size}}` 插值）

## 注意事项

- System 页的 GPU toggle 是**即时生效**的（单独 PATCH `gpuDisabledDevices`），不需要 Save 按钮
- Settings 页的 GPU state（`updateGpuDevice`、`gpuDevices` 相关）从 settings-page 删除，
  但 `SettingsData.gpuDevices` type 保留（system-page 也用这个 type）
- `getStorageStats` / `cleanOrphans` / `StorageStats` / `formatBytes` 从 settings-page import 删除，
  system-page 重新引入

## Out of Scope

- 显存实时占用（后续单独做）
- Storage 清理预览（列出具体文件路径）
- 其他 settings 页内容的调整

## Acceptance Criteria

- [ ] `/admin/system` 可访问，显示 GPU Devices 和 Storage 两个 section
- [ ] GPU toggle 即时生效（PATCH 成功后无需手动保存）
- [ ] 孤儿缓存清理前弹出确认 dialog，显示大小和数量
- [ ] 取消不执行清理；确认后执行，结果 toast.success
- [ ] Settings 页不再显示 GPU Devices 和 Storage section
- [ ] Admin 导航出现 "系统" / "System" 入口
- [ ] `npm run build` zero errors
- [ ] 中英文 i18n 完整
