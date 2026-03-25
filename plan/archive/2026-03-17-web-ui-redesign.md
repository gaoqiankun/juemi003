# Web UI 专业化改造
Date: 2026-03-17
Status: done / Commits: uncommitted

## Goal
把现有单文件测试台（static/index.html，1995 行）改造成面向外部用户的专业 Web 界面，
对标 Meshy/Tripo/Hunyuan 3D 商业平台的设计质感，但保持功能范围不变。

## Key Decisions
- **不引入构建链**：全部依赖 CDN（Tailwind、Lucide、Three.js），FastAPI 静态文件挂载方式不变
- **路由形态**：改成 Hash Router 单页壳，页面为 `/#/`、`/#/gallery`、`/#/settings`
- **状态组织**：生成页不再混任务列表，只围绕一个当前任务做 idle / uploading / processing / completed / failed 五态切换
- **3D 查看器**：继续用 Three.js + GLTFLoader + OrbitControls，但改成 fetch+blob URL 加载并加重试，修新任务 artifact 刚生成时的预览竞态
- **文件拆分**：`index.html` 只保留 SPA shell，业务按 `router.js` / `generate.js` / `gallery.js` / `settings.js` / `viewer3d.js` 切分
- **交互修复**：取消按钮严格按 `gpu_queued` 可取消规则控制；Drawer/Confirm 改成显式焦点归位，不再靠 `aria-hidden` 切换

## Changes
| 文件 | 变更 |
|------|------|
| static/index.html | 改成 SPA 壳：固定顶部 Nav、路由容器、Drawer、Confirm、Toast |
| static/router.js | 新建：Hash Router、全局状态、API 调用、SSE/轮询、Drawer/Confirm/Toast、页面渲染协调 |
| static/generate.js | 新建：生成页五态模板 |
| static/gallery.js | 新建：图库网格、筛选 Tab、详情 Drawer 模板 |
| static/settings.js | 新建：设置页表单、API Key toggle、/ready 状态面板 |
| static/viewer3d.js | 保留并增强：GLB fetch+blob URL 加载、重试、缩略图复用 |

## UI 设计要点
- Header：Logo 左、三段式导航右、全局连接状态点常驻
- 生成页：大 Hero 上传区 + 单任务状态机，不出现历史任务卡片
- 图库页：历史任务卡片网格 + 全/处理中/完成/失败筛选 + Drawer 详情
- 设置页：API Key 密文/明文切换、Base URL 保存、/ready 状态点
- Toast、Drawer、Confirm 都保留深色玻璃态视觉
- 响应式：桌面与移动端都能完整切路由、开 Drawer、操作按钮

## 保留的全部功能
- API Key 本地存储（localStorage）
- API Base URL 可配置
- /ready 健康检查
- 图片上传（/v1/upload）+ 任务创建（/v1/tasks POST）
- 任务列表分页（/v1/tasks GET）
- SSE 实时进度（/v1/tasks/{id}/events）
- 任务详情（/v1/tasks/{id} GET）
- 任务删除（DELETE /v1/tasks/{id}）
- GLB artifact 下载 + Three.js 内嵌预览

## Notes
- 本次验证用本地 mock server + Playwright 实测：设置页保存 toast、生成功能 completed 切态、图库路由与 Drawer 均跑通
- `/ready` 在模型未 ready 时会显示红点；mock 任务成功后可切成绿色“服务可用”
- 删除确认层改成显式 confirm 状态，成功删除时会先清空 confirm，再移除任务，避免残留遮罩
- 为避免 `aria-hidden` 警告，Drawer/Confirm 改为 `hidden + inert + focus restore` 管理
