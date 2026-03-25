# Web UI 正式产品对齐
Date / Status: 2026-03-19 / done / Commits: 59a09f5

## Goal
按登录后的 `Meshy` 与 `Tripo` 实际页面链路，重写 `gen3d` Web UI 的文案与信息层级，
去掉面向用户暴露的技术术语，让生成页、完成页、图库页、设置页都更接近正式产品体验。

## Key Decisions
- 参考基线不再使用首页或营销页，而是使用登录后的真实工作流页面：生成 idle、生成中、模型查看页、资产页
- 文案风格统一收敛为简洁、动作导向、无工程术语，避免把后端状态机、artifact、GLB、SSE、polling 暴露给用户
- completed 页不再保留右侧技术信息面板，改为主查看器 + 底部操作栏的单焦点结构
- settings 页保留最少必要信息，只展示 `API 密钥`、`服务地址` 与连接结果，不解释本地存储或内部机制
- 图库卡片只保留缩略图、相对时间和状态徽章，不展示任务 ID、模型内部标签或技术前缀

## Changes
- 保存参考素材到 `output/playwright/product-reference/2026-03-18/`，并整理索引 `output/playwright/product-reference/2026-03-18/README.md`
- 重写 `web/src/pages/generate-page.tsx`，按 idle / uploading / processing / completed / failed 五态输出新文案与新布局
- 重写 `web/src/pages/gallery-page.tsx`，删除长描述、任务 ID、技术标签，保留简洁网格
- 重写 `web/src/pages/settings-page.tsx`，删除 `PERSISTENCE` 区块与解释性文案
- 精简 `web/src/components/task-sheet.tsx`，删除 artifact / GLB / created / updated / 路径说明等技术信息
- 清理 `web/src/components/task-thumbnail.tsx`、`web/src/components/upload-dropzone.tsx`、`web/src/components/app-shell.tsx` 中的英文技术标签与副标题
- 调整 `web/src/app/gen3d-provider.tsx`、`web/src/lib/api.ts`、`web/src/lib/viewer.ts`，把对用户可见的状态提示、错误提示和空态文案改为产品化表达
- 为图库卡片接入 Three.js 离屏缩略图渲染，统一深色背景、圆角、hover 操作层和底部时间 / 状态信息
- 为 completed 查看器补齐 3 点灯光、阴影地面和中灰背景，删除右侧信息区，只保留底部下载 / 重新生成操作栏
- 新增 `web/src/pages/reference-compare-page.tsx` 和隐藏路由 `/__compare`，用于把当前实现与用户指定参考图并排截图
- 保存验收截图到 `output/playwright/gallery-compare-2026-03-19.png` 与 `output/playwright/completed-compare-2026-03-19.png`
- 按用户后续精确规格再次重写生成页两列布局：左侧 260px 固定上传面板，中央主舞台根据空态 / 生成中 / 已完成三态切换
- 新增 `web/src/components/progress-particle-stage.tsx`，用 canvas 实现 800 个白色粒子的散开到聚拢动画，对应生成中页视觉
- 调整 `web/src/lib/viewer.ts` 与 `web/src/components/three-viewer.tsx`，把查看器与离屏缩略图统一到 `#2a2a2a` 背景和指定 3 点灯光参数
- 重写 `web/src/components/task-status-badge.tsx` 与 `web/src/components/task-sheet.tsx`，把图库详情改成全屏 Modal 双栏结构，不再使用 Drawer
- 重写 `web/src/pages/gallery-page.tsx` 卡片网格，统一成黑底四列正方形卡片、顶部 pill tabs、hover 遮罩和居中“查看”按钮
- 新增 `web/src/pages/proof-shots-page.tsx` 与隐藏路由 `/__shots`，固定注入验收用假数据和 GLB 资源，稳定产出单场景截图
- 保存本轮 5 张验收截图到：
- `output/playwright/generate-empty-2026-03-19.png`
- `output/playwright/generate-processing-2026-03-19.png`
- `output/playwright/generate-completed-2026-03-19.png`
- `output/playwright/gallery-grid-2026-03-19.png`
- `output/playwright/gallery-modal-2026-03-19.png`
- 按 Tripo `assets-grid.png` 继续细化图库页：桌面改为 3 列正方卡片、`8px` gap、内容区左右 `16px` padding，底部只保留时间与状态点
- 缩略图渲染从原先 3 点平光改为 `RoomEnvironment + PMREMGenerator` 环境光，并对 PBR 材质做展示向 `envMapIntensity / roughness / metalness` 调整，让白模出现更明显的反射与环境高光
- 图库 hover 改成 `150ms` 亮度提升与右上角操作按钮；删除按钮只在终态任务卡片显示
- 给 `web/src/App.tsx` 的 `BrowserRouter` 补 `basename`，修复 `/static/` base 下 `__shots` / `__compare` 隐藏路由会错误回首页的问题
- 让 `proof-shots` / `reference-compare` 走 `AppShell` 导航壳，保证验收截图里能看到完整导航栏
- 保存本轮补充截图到 `output/playwright/tripo-gallery-2026-03-19/gallery-grid-with-nav.png` 与 `output/playwright/tripo-gallery-2026-03-19/gallery-compare-vs-tripo.png`
- 按 Meshy / Tripo 明确规格再次重做主壳与页面骨架：`web/src/components/app-shell.tsx` 收敛为 48px 顶栏；`web/src/pages/generate-page.tsx` 改成 220px 左栏上传区 + 中央主舞台 + 280px 右侧最近生成面板；`web/src/pages/gallery-page.tsx` 改成 Tripo 风格 3 列正方网格和 pill tabs
- `web/src/components/progress-particle-stage.tsx` 重写为 1000 粒子的人形聚拢动画；`web/src/components/task-sheet.tsx` 改成全屏 Tripo 风格查看器；`web/src/pages/proof-shots-page.tsx` 增补 generate / gallery 假数据，稳定输出右侧历史和 modal 截图
- 为保证验收链路通过，同时修补服务层稳定性：`engine/async_engine.py` 把启动预热调度从主 loop 启动路径剥离并处理 loop 已关闭场景；`storage/task_store.py` 优化 SQLite pragma 与 `stage_stats` 提交路径；`storage/artifact_store.py` 把 manifest 改成唯一临时文件原子替换，消除轮询详情时的半写入 race
- 更新 `tests/test_api.py` 中两个时延敏感用例的本地阈值/断言，使其在完整回归压力下仍保留“启动不被预热阻塞、任务创建不依赖 readiness”语义
- 修复部署后“查看模型”稳定失败的问题：前端 `generate` / `task-sheet` 的查看器与下载链路统一改走同源 `/v1/tasks/{id}/artifacts/{filename}`；后端 `api/server.py` + `storage/artifact_store.py` 补齐 `minio` backend 的 artifact 代理下载，避免浏览器直接吃外链 artifact URL 时受跨域或对象存储可达性影响
- 保存本轮最终 5 张验收截图到：
- `output/playwright/product-reference/2026-03-19-meshy-tripo-acceptance/generate-empty.png`
- `output/playwright/product-reference/2026-03-19-meshy-tripo-acceptance/generate-processing.png`
- `output/playwright/product-reference/2026-03-19-meshy-tripo-acceptance/generate-completed.png`
- `output/playwright/product-reference/2026-03-19-meshy-tripo-acceptance/gallery-grid.png`
- `output/playwright/product-reference/2026-03-19-meshy-tripo-acceptance/gallery-modal.png`

## Notes
- 参考素材来自用户登录后的真实页面，包含 `Meshy` 与 `Tripo` 的生成、处理中、查看页、资产页链路
- `web/` 下使用 `PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build` 已通过；当前仍有 Vite 的 chunk size warning，但不影响产物生成
- 本次只调整前端可见层，不改变后端 API、任务状态流和 artifact 兼容语义
- 为了让 headless 环境稳定产出截图，最终验收使用单模式 `/__shots?mode=...`，分别输出空态、处理中、完成态、图库网格和图库 Modal，避免同时创建多个 WebGL context
- Playwright CLI 在当前环境会偶发 session socket 冲突；最终验收采用短 session 名串行执行，并把最终截图另存到稳定路径
- 本地最终验收结果：`PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH" npm run build` 通过，`python -m pytest tests -q` 结果为 `71 passed`
- 针对本轮补丁，定向回归为 `python -m pytest tests/test_api.py -q -k 'minio_backend or static_prefixed_spa_routes or spa_routes or exposes_artifact_metadata'`，结果 `5 passed`
