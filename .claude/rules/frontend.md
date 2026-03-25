# Frontend Rules

> 当修改 `web/` 目录下任何文件时适用。

## 命令

```bash
cd web && npm run build          # 必须零错误
npm run dev -- --host 127.0.0.1 --port 5173   # 纯样式调试
```

## 布局规则

| 页面类型 | 写法 |
|---------|------|
| Canvas 页（Generate/Viewer）| `-mx-4 -my-6 md:-mx-6` 突破 shell padding；画布 `absolute inset-0` |
| 内容页（Gallery/Setup/Admin）| `max-w-7xl mx-auto` |

浮动面板固定写法：
```
pointer-events-none（外层）> pointer-events-auto（面板）
bg-surface-glass backdrop-blur-xl shadow-soft border border-outline rounded-2xl
```

**新增代码**不引入 `sm:` / `lg:` / `xl:` 响应式前缀（`md:-mx-6` Canvas 负边距除外）；存量代码不强求清理

## 间距与尺寸

- 页面级间距：`gap-4`，卡片内：`gap-3`，字段内：`gap-1.5`
- 卡片 padding：`p-4`
- 操作按钮：统一 `size="sm"`（h-8），**不允许自定义 `h-*`**
- 圆角：面板 `rounded-2xl` → 按钮/卡片 `rounded-xl` → 小元素 `rounded-lg`

## 组件

- Select / Dialog：Radix UI（`@/components/ui/`，已封装好）
- 图标：lucide-react，不引入其他图标库
- Toast：sonner，直接调用 `toast.success()` / `toast.error()`（`<Toaster>` 已在 `main.tsx` 挂载）

## i18n（高优先级约束）

- 任何用户可见文案改动**必须同时更新** `en.json` 和 `zh-CN.json`
- 语言选项始终使用 `nativeName`（原生语言名称），不用 `name`
- 两个文件的 key 集合必须完全一致

## 验收标准

- `npm run build` 零错误
- 修改了文案 → 两个 i18n 文件均已更新
- 没有引入新的 `sm:` / `md:` / `lg:` 响应式前缀（Canvas 负边距除外）
