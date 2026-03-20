# i18n 文案清理
Date / Status: 2026-03-21 / done / Commits: n/a

## Goal
清理 `web/src/i18n/en.json` 与 `web/src/i18n/zh-CN.json` 中的开发口吻文案，统一为正式产品表达，并同步修正 Setup 默认服务地址与少量页面硬编码文本。

## Key Decisions
- 所有用户可见文案去掉 `mock`、`placeholder`、`stitch-synced`、`localStorage` 等开发者表述
- Setup 页说明改为面向真实用户的连接指引，并把默认服务地址改为 `window.location.origin`
- 补齐少量未进入 i18n 的页面硬编码文本，保证中英文对应准确
- i18n 内部 key 也去掉明显开发痕迹：`mockTitles` / `mockPrompts` / `mockUploadReady` 改为中性命名

## Changes
- 更新 `web/src/i18n/en.json` 与 `web/src/i18n/zh-CN.json`，逐页重写 Admin/User 文案
- 更新 `web/src/data/user-mocks.ts`，Setup 默认服务地址改为运行时 `window.location.origin`
- 更新 `web/src/pages/viewer-page.tsx`、`dashboard-page.tsx`、`models-page.tsx`、`api-keys-page.tsx`、`generate-page.tsx`，把少量硬编码展示文本改为走 i18n

## Notes
- 已验证 en / zh-CN key 集合一致
- 已验证 `npm run build` 通过
