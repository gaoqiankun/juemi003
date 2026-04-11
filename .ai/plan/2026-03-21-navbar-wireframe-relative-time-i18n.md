# 导航栏对齐 + Wireframe 可见性 + 相对时间 i18n
Date: 2026-03-21
Status: done

Date / Status: 2026-03-21 / done / Commits: not committed in this session
## Goal
- 让用户端 header 内容与页面主内容保持同一对齐基线。
- 提升 `wireframe` 显示模式下线框可见性，确保与 texture/clay 有明显区分。
- 让生成页和图库页的相对时间文案跟随语言切换（中文/英文）。

## Key Decisions
- `user-shell` header 内容容器去掉 `mx-auto + max-w`，保持与已全宽的 `main` 一致。
- `wireframe` 模式继续保留 clay 底色结构参照，但增强对比度：
  - 线框颜色改深（`#2a2d35`）
  - 线框不透明度提升到 `1`
  - wireframe 模式下底色更亮且环境反射更弱，避免线框被吞没
- `formatRelativeTime` 扩展 locale 参数并在页面调用处传入 `i18n.resolvedLanguage`。

## Changes
- `web/src/components/layout/user-shell.tsx`
  - header 内部容器改为：`flex h-16 w-full items-center justify-between gap-4 px-4 md:px-6`
- `web/src/lib/viewer.ts`
  - wireframe 覆盖线框材质颜色：`#9199a8` → `#2a2d35`
  - 线框透明度：`0.95` → `1`
  - wireframe 模式底材质调亮，降低 envMap 反射，提升线框对比
- `web/src/lib/format.ts`
  - `formatRelativeTime(value, locale?)` 支持按 locale 输出中英文相对时间
  - 英文下支持如 `yesterday` / `3 days ago`（由 `Intl.RelativeTimeFormat("en", { numeric: "auto" })` 生成）
- `web/src/pages/generate-page.tsx`
  - 最近记录时间显示改为 `formatRelativeTime(task.createdAt, i18n.resolvedLanguage)`
- `web/src/pages/gallery-page.tsx`
  - 卡片时间显示改为 `formatRelativeTime(task.createdAt, i18n.resolvedLanguage)`

## Notes
- 构建验证通过：
  - `cd web && PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build`
