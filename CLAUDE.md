# Cubie · Claude 架构师记忆

> 子仓库：`./gen3d/`
> 最后更新：2026-03-21
> 产品名：**Cubie**（不带 3D 后缀，3D 仅用于说明领域）

---

## 项目定位

可私有部署的开源 3D 生成服务，对标 Meshy / Tripo3D 商业产品。
类比 ComfyUI / InvokeAI 在图像生成领域的地位。

- 目标用户：专业设计师、独立开发者、企业私有化部署
- 主平台：Linux / Windows + NVIDIA GPU（CUDA）
- 部署方式：Portable 安装包（主推）/ Pinokio / Docker
- 测试环境：https://gen3d.frps.zhifouai.com

---

## 当前状态（2026-03-21）

后端测试基线：`python -m pytest tests -q` → **116 passed**

### v0.1 模块进度

| 模块 | 状态 |
|------|------|
| M1 · 品牌 & 开源化基础 | ✅ 完成 |
| M2 · Admin Panel（5页 双主题 i18n） | ✅ 完成（真实化：全量 API + 前端接入） |
| M2.5 · 用户侧页面 | ✅ 功能完成，UI 商业级打磨中 |
| M3 · HunYuan3D Provider | ✅ 完成（mock + real，11 新测试） |
| M4 · 安装体验（Pinokio + 脚本）| 🔲 待开始 |
| M5 · 文档完善 | 🔲 待开始 |
| M6 · 发布前 QA & 清理 | 🔲 待开始 |

### Web UI 打磨进度（M2.5 细化）

已完成 5 轮打磨（3/21），已提交的改进：
- 全站品牌统一：Cubie，术语统一为 Assets/资产
- 导航：Logo + Workspace / Assets + 语言切换（Languages 图标，原生语言名）+ 主题 + 设置
- Generate 页：全屏 canvas + 浮动玻璃面板（配置+最近任务），负边距突破 shell padding
- Viewer 页：全屏 canvas + 右侧浮动玻璃侧边栏，Task ID 标题，输入图预览，格式下拉，删除确认
- Gallery 页：卡片直接跳转 Viewer（删除了 TaskSheet），max-w-7xl 居中
- 模型查看器工具栏：显示模式 / 旋转 / 网格 / 重置 / 灯光 / 背景色
- 背景色选择器：紧凑圆点预设 + 自定义取色 + 跟随主题
- 亮色/暗色主题适配：viewer 背景、网格线、线框色

第 6 轮已完成（3/21）：工具栏去嵌套框、Lightbulb 灯光图标、阴影开关、背景选择器紧凑布局、Setup 精简、i18n 文案修正

---

## Web UI 设计规范

### 布局模式

| 类型 | 用法 | 关键 class |
|------|------|-----------|
| Canvas 页（Generate/Viewer）| 全屏无边界画布 + 浮动玻璃面板 | `-mx-4 -my-6 md:-mx-6` 突破 shell padding，`absolute inset-0` 画布 |
| 内容页（Gallery/Setup）| 常规流式布局 | `max-w-7xl mx-auto` 居中 |

### 浮动面板

```
pointer-events-none（外层禁止事件）
  → pointer-events-auto（面板恢复事件）
    → bg-surface-glass backdrop-blur-xl shadow-soft border border-outline rounded-2xl
```

### 组件约定

- Select / Dialog：使用 Radix UI（`@/components/ui/select`、`react-dialog`）
- i18n：react-i18next，`en.json` + `zh-CN.json`
- 图标：lucide-react
- 语言选项始终显示原生名称（`nativeName` 字段）
- 圆角层级：面板 `rounded-2xl`，按钮/卡片 `rounded-xl`，小元素 `rounded-lg`

### 3D 查看器

- `ThreeViewer` → `Viewer3D`（viewer.ts），支持 texture/clay/wireframe 模式
- 背景色：`useViewerColors` hook 提供主题色，用户可手动选预设或自定义
- studio 灯光：可调光强和角度
- 阴影：contactShadow + shadowFloor，可开关（第 6 轮新增）

---

## 关键路径

| 文件/目录 | 说明 |
|----------|------|
| `AGENTS.md` | AI Coder 执行指南 |
| `docs/PLAN.md` | 架构基线 |
| `plan/` | 规划日志（79 个文件，最新 3/21） |
| `config.py` / `serve.py` | 后端入口 |
| `api/` / `engine/` / `model/` / `stages/` | 后端核心 |
| `storage/model_store.py` | 模型定义 CRUD（model_definitions 表） |
| `storage/settings_store.py` | 系统设置持久化（system_settings 表） |
| `storage/task_store.py` | 任务存储 + 聚合统计 |
| `storage/api_key_store.py` | API Key CRUD + 使用量追踪 |
| `web/src/lib/admin-api.ts` | Admin API client |
| `web/src/pages/` | 前端页面（generate/gallery/viewer/setup + 5 个 admin 页） |
| `web/src/components/model-viewport.tsx` | 模型查看器+工具栏 |
| `web/src/lib/viewer.ts` | Three.js 渲染器 |
| `web/src/styles/tokens.css` | 设计 token（CSS 变量） |
| `web/src/i18n/` | 多语言文件 |

---

## Provider 状态

| Provider | 状态 |
|---------|------|
| `mock`（MockTrellis2Provider）| ✅ 可用 |
| `real`（Trellis2Provider）| ✅ 可用 |
| `hunyuan3d`（HunYuan3D-2）| ✅ mock + real 可用 |

---

## 暂缓事项

| 事项 | 目标版本 |
|------|---------|
| 背景图/HDRI 支持 | v0.2 |
| Phase D 多机 Worker | v0.2 |
| Mac Apple Silicon | v0.2 |
| Launcher GUI | v0.2 |
| E15-B 外部后端接入示例 | 文档示例 |

---

## 技术债

- IP 白名单校验：已存 IP，校验逻辑待 nginx 路径稳定后开启
- GPU 细粒度进度 hook：`gpu_ss/gpu_shape/gpu_material` 是语义占位
- GPU scheduler：简单 FIFO，`max_batch + deadline` 调度未实现
- 取消运行中任务：仅支持 `gpu_queued` 状态
