# Admin 面板布局审计结果
Date: 2026-03-23
Status: done

## 1. admin-shell.tsx 整体布局

| 位置 | class | 含义 |
|------|-------|------|
| 外层 :210 | `lg:grid lg:grid-cols-[280px_minmax(0,1fr)]` | lg 起双列，lg 以下单列堆叠 |
| 侧边栏 :211 | `lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r` | lg 起 sticky 侧栏，移动端顶部块 |
| Header :255 | `flex-col gap-4 px-6 py-5 xl:flex-row xl:items-center xl:justify-between` | 默认竖排，xl 起横排 |
| Main :335 | `max-w-[1440px] mx-auto px-6 py-6 gap-6` | 1440px 居中，24px 边距和间距 |

## 2. 各页面布局

| 页面 | 网格断点 | 卡片 padding | 卡片间 gap | 字段间 gap | max-width | Button size |
|------|---------|-------------|-----------|-----------|-----------|-------------|
| tasks | md:2 xl:4, xl:flex-row | p-5=20px | gap-4=16px / gap-6=24px | gap-2=8px | 搜索框 max-w-sm=384px | 无 Button |
| models | 无栅格断点 | p-5=20px | gap-6=24px | gap-1.5=6px / gap-2.5=10px | max-w-xs=320px(错误提示) | sm + 自定义 h-7=28px |
| api-keys | xl:[1.5fr_22rem] | p-5=20px | gap-4=16px / gap-6=24px | gap-1.5=6px / gap-2=8px | 无 | 全部 sm |
| settings | md:2 xl:3, md:2(HF) | p-5=20px | gap-4=16px / gap-6=24px | gap-2=8px / gap-3=12px | 无 | 全部 sm |

## 3. 共享组件

### Button size 变体
| size | class | 像素 |
|------|-------|------|
| default | h-11 px-4 py-2.5 | 44px |
| sm | h-8 rounded-md px-2.5 text-xs | 32px |
| lg | h-12 px-5 text-sm | 48px |
| icon | h-10 w-10 p-0 | 40x40px |

### TextField/Input 高度
h-11 = 44px

### Card 默认样式
rounded-lg(8px) border border-outline shadow-soft bg-surface-container-highest，无默认 padding

## 4. 响应式断点使用汇总

Tailwind 默认断点：sm=640 md=768 lg=1024 xl=1280

- **sm:** 未使用
- **md:** settings 字段 2 列、HF 双列、tasks 统计卡 2 列
- **lg:** admin-shell 侧栏+内容双列布局
- **xl:** header 横排、tasks 统计卡 4 列、api-keys 双栏、settings 字段 3 列
