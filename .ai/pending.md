# 跨角色待处理项

> Backend 改动 API Contract 后在此登记；Frontend 开工前先检查，处理完删除对应条目。
> 格式：`- [ ] [日期] 描述 —— 影响文件/接口`

---

- [ ] [2026-03-30] Admin 模型接口新增依赖字段与查询接口：`GET /api/admin/models?include_pending=true` 的模型记录新增 `deps`（数组）；新增 `GET /api/admin/deps` 与 `GET /api/admin/models/{id}/deps` —— 影响 `web/src/lib/admin-api.ts` 与 models 页面数据适配
