# Admin: manual model unload
Date: 2026-04-16
Status: done

## Goal

在模型管理页面加上手动卸载已加载模型的功能。

## Changes

### 1. `api/server.py` — 新增 unload endpoint
```
POST /api/admin/models/{model_id}/unload
```
- model not found → 404
- runtimeState == not_loaded → 400 "model is not loaded"
- 调 `model_registry.unload(model_id)` → 返回 `{id, runtimeState}`

### 2. `web/src/lib/admin-api.ts`
新增 `unloadModel(id)` — POST `/api/admin/models/{id}/unload`

### 3. `web/src/hooks/use-models-data.ts`
新增 `requestModelUnload(modelId)` — 同 `requestModelLoad` 模式：setBusy → unloadModel → loadModels → clearBusy
导出 `requestModelUnload`

### 4. `web/src/pages/models-page.tsx`
- 新增 `handleUnload(model)` callback
- 在 Load 按钮旁加 Unload 按钮：`runtimeState === "ready"` 时显示，loading/busy 时 disabled

### 5. `web/src/i18n/en.json` + `zh-CN.json`
`models.list.unload`: "Unload" / "卸载"

## Acceptance Criteria

- [ ] POST /api/admin/models/{id}/unload 正常返回，runtimeState 变为 not_loaded
- [ ] 未加载模型调 unload → 400
- [ ] 前端 Unload 按钮仅在 runtimeState=ready 时可用
- [ ] 操作后列表自动刷新
- [ ] 全部后端测试通过
