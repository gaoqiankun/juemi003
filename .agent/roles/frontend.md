# 前端工程师

> 先读项目根目录的 `AGENTS.md`，再读本文件。

**职责**：React/TypeScript 实现——pages、components、hooks、lib、i18n

## 启动检查

1. 查 `.agent/pending.md`，有待处理的 API Contract 变更则优先同步
2. 明确本次任务改哪些页面/组件
3. 确认 Node 版本（系统默认版本可能不兼容）：
   ```bash
   export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH"
   ```
4. `cd web && npm run build` 确认零错误（基线）

## 改动范围

**可以改**：`web/` 目录下所有文件

**不能改**：所有 Python 文件

## 页面路由表

| 文件 | 路由 | 备注 |
|------|------|------|
| `setup-page.tsx` | `/setup` | |
| `generate-page.tsx` | `/generate` | Canvas 页 |
| `gallery-page.tsx` | `/gallery` | |
| `viewer-page.tsx` | `/viewer/:taskId` | Canvas 页 |
| `tasks-page.tsx` | `/admin/tasks` | Admin |
| `models-page.tsx` | `/admin/models` | Admin |
| `api-keys-page.tsx` | `/admin/api-keys` | Admin |
| `settings-page.tsx` | `/admin/settings` | Admin |
| `proof-shots-page.tsx` | 未挂载 | 不要挂路由 |
| `reference-compare-page.tsx` | 未挂载 | 不要挂路由 |

## 设计规范

**布局**
- Canvas 页：`-mx-4 -my-6 md:-mx-6` 突破 shell；画布 `absolute inset-0`；浮动面板 `pointer-events-none > pointer-events-auto`，样式 `bg-surface-glass backdrop-blur-xl shadow-soft border border-outline rounded-2xl`
- 内容页：`max-w-7xl mx-auto`
- **新增代码**不引入 `sm:` / `md:` / `lg:` / `xl:` 响应式前缀（`md:-mx-6` Canvas 负边距除外）；存量代码不强求清理

**间距与尺寸**：页面级 `gap-4`，卡片内 `gap-3`，字段内 `gap-1.5`；卡片 `p-4`；按钮 `size="sm"`，禁止自定义 `h-*`；圆角 `rounded-2xl → rounded-xl → rounded-lg`

**组件**：Select/Dialog 用 Radix UI（`@/components/ui/`）；图标 lucide-react；Toast 用 `toast.success/error()`（sonner，已挂载）

**组件不存在时**：先查 `web/src/components/ui/` 有无可复用的；没有则用原生 HTML 元素 + Tailwind 样式实现，不引入新的第三方组件库；若逻辑复杂需封装，在 `web/src/components/ui/` 新建文件，命名和现有组件保持一致风格。

**Admin 表格操作列**：单 `<td>` + `flex items-center gap-2`；按钮始终渲染用 `disabled` 表达不可用；错误信息用 `title` + `cursor-help`

## 代码质量

**文件体积**
- 新建组件：超过 300 行前主动拆分
- 改动已有文件：改后超过 500 行，停下来，在 plan 文件里标注原因，由架构师决定是当场拆还是记技术债

**职责拆分**
- 页面组件只负责布局和状态编排，业务逻辑提取到 `hooks/` 自定义 Hook
- 可复用 UI 片段超过 50 行，提取到 `components/` 独立文件
- 单个 Hook 超过 80 行，考虑拆分

## i18n（必须执行）

任何用户可见文案改动，**必须同时更新** `src/i18n/en.json` 和 `src/i18n/zh-CN.json`，两文件 key 集合必须完全一致，语言选项用 `nativeName`。

UI 打磨任务参考 `.claude/skills/ui-polish/SKILL.md`。

## 验收

```bash
cd web && npm run build    # 零错误
cd web && npm run lint     # 存量 45 条，新改动不得引入新问题

# 顺手检查：改动文件有无超标（> 500 行在 plan 里标注）
find web/src -name "*.tsx" -o -name "*.ts" | xargs wc -l | sort -rn | head -10
```

## 汇报格式

- 改了哪些页面/组件
- i18n 是否同步更新
- 视觉变化描述
- 若处理了 pending.md 中的条目，标注已删除
- **下游交接**（若后续任务依赖本次产出）：列出新增组件、状态结构变化、需后端感知的字段
