# Cubie · AI Coder 执行指南

> 开始任何任务前，先读本文件和相关 `plan/*.md`。

## 1. 工作方式

- 不执行任何修改 git 树的操作（`git add/commit/push/rebase`），完成后只汇报结果
- 只读 git 操作（`status/log/diff`）不受限
- 不修改 `ios/` 和 `server/` 的文件
- 完成任务后更新或新建 `plan/` 文件

## 2. 项目概况

**Cubie** — 开源 3D 生成服务，FastAPI 后端 + React 前端

- 后端：Python/FastAPI，provider 模式（mock/real/hunyuan3d）
- 前端：React + Vite + TypeScript，`web/` 目录
- 部署：Docker，FastAPI 直接服务 `web/dist/`

### 目录结构

```
gen3d/
├── config.py / serve.py          # 后端入口
├── api/ / engine/ / model/       # 后端核心
├── stages/ / storage/            # 任务管线、存储
├── observability/ / tests/       # 监控、测试
├── web/                          # React SPA
│   ├── src/pages/                # generate/gallery/viewer/setup
│   ├── src/components/           # 共享组件
│   ├── src/lib/                  # 工具库（viewer.ts 等）
│   ├── src/styles/tokens.css     # 设计 token
│   └── src/i18n/                 # en.json + zh-CN.json
├── docker/ / scripts/
├── docs/PLAN.md                  # 架构基线
└── plan/                         # 规划日志
```

## 3. Web 前端设计规范

### 布局

- **Canvas 页**（Generate/Viewer）：全屏无边界画布 + 浮动玻璃面板
  - 负边距 `-mx-4 -my-6 md:-mx-6` 突破 UserShell padding
  - 画布 `absolute inset-0`
  - 面板 `pointer-events-none` 外层 → `pointer-events-auto` 面板
  - 面板样式 `bg-surface-glass backdrop-blur-xl shadow-soft border border-outline rounded-2xl`
- **内容页**（Gallery/Setup）：`max-w-7xl mx-auto` 居中

### 组件

- Select / Dialog：Radix UI（`@/components/ui/select`、`react-dialog`）
- 图标：lucide-react
- i18n：react-i18next，修改任何用户可见文案必须同时更新 `en.json` 和 `zh-CN.json`
- 语言选项始终使用 `nativeName`（原生语言名称）

### 圆角层级

面板 `rounded-2xl` → 按钮/卡片 `rounded-xl` → 小元素 `rounded-lg`

### 3D 查看器

- `ThreeViewer`（three-viewer.tsx）→ `Viewer3D`（viewer.ts）
- 显示模式：texture / clay / wireframe
- 背景：预设色圆点 + 自定义取色 + 跟随主题，通过 `useViewerColors` hook
- 灯光：studio 双光源，可调光强和角度
- 阴影：contactShadow + shadowFloor，可开关

## 4. 当前实现边界

以下功能尚未完成，不要误标为已完成：

- `model/hunyuan3d/provider.py`：`NotImplementedError` 占位
- GPU scheduler：简单 FIFO，无 `max_batch + deadline` 调度
- GPU worker：进程内 wrapper，非独立多进程
- 取消只支持 `gpu_queued` 状态
- `observability/metrics.py`：仅 readiness gauge

## 5. 本地开发

```bash
# 后端
cd ./gen3d
python -m pip install -r requirements.txt
python serve.py
python -m pytest tests -q   # 基线 85 passed

# 前端
cd ./gen3d/web
export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH"
npm ci && npm run build     # 输出到 web/dist/
```

- 联调：构建前端后运行 `python serve.py`，通过 FastAPI 验证
- 纯样式调试：`npm run dev -- --host 127.0.0.1 --port 5173`
- 无 CORS 中间件，真实 API 流程以 FastAPI 服务为准

## 6. 修改注意

- 保持 API、状态流、artifact 语义兼容
- 文档、代码、plan 同步更新
- `npm run build` 零错误是基本验收条件
