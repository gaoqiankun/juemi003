# Cubify 3D · 开源转型总规划

Date: 2026-03-20
Status: planning

---

## Goal

将 gen3d 从 hey3d 内部服务转型为独立开源项目 **Cubify 3D**——
任何人可以在自己的 GPU 服务器上一键部署，生成质量和使用体验对标 Meshy / Tripo3D 等商业产品。

---

## 战略定位

| 维度 | 定位 |
|------|------|
| 类比 | ComfyUI / InvokeAI，但专注 3D 生成 |
| 目标用户 | 专业设计师、独立开发者、企业私有化部署 |
| 主平台 | Linux / Windows + NVIDIA GPU（CUDA）|
| 未来扩展 | Mac Apple Silicon（via ollama 类工具，不在 v0.1）|
| 开发阶段部署 | Docker（不变）|
| 正式发布安装 | Portable 安装包（主推）/ Pinokio / Docker |

---

## v0.1 发布目标

v0.1 是首个公开版本，定义为**可用、易装、质量稳定**：

- ✅ 已有：TRELLIS2 生成、React Web UI、任务管理、API
- 🔲 待做：HunYuan3D provider 实现
- 🔲 待做：品牌重命名（Cubify 3D）
- 🔲 待做：开源化清理（文档、License、去 hey3d 耦合）
- 🔲 待做：Model 管理 UI（首次运行引导 + 下载）
- 🔲 待做：安装体验（Pinokio + 脚本）
- 🔲 待做：公开文档（README、部署文档、API 文档）

---

## 模块拆解（按执行顺序）

### M1 · 品牌 & 开源化基础
优先级：🔴 最高，其他模块依赖此完成

- 仓库重命名逻辑上改为 cubify3d（目录、包名、配置 key、日志 prefix 等）
- 项目显示名统一为 "Cubify 3D"
- 添加 LICENSE 文件（建议 Apache 2.0，允许商业使用但保留归属）
- 去掉所有 hey3d 内部引用（env 变量命名、注释里的内部 URL 等）
- 更新 README.md：项目简介、快速开始、截图占位

---

### M2 · HunYuan3D Provider 实现
优先级：🔴 高（差异化核心，v0.1 必须有两个 provider）

现状：`model/hunyuan3d/provider.py` 是 `NotImplementedError` 占位

目标：
- 完整实现 HunYuan3D-2（Tencent 开源模型）生成 pipeline
- 与 TRELLIS2 并列为可选 provider，配置切换
- 生成质量验收：输出 .glb 可正常加载，preview.png 渲染正常
- 补充对应 tests

---

### M3 · Model 管理 UI
优先级：🔴 高（用户体验核心，无此设计师无法上手）

**首次运行 Setup Wizard（浏览器内）：**
- 启动时检测模型权重是否存在
- 未检测到 → 强制进入 Setup Wizard 页面
- Wizard 展示：可选模型列表（模型名、质量说明、VRAM 要求、文件大小）
- 用户勾选 → 点「开始下载」→ 实时进度条 → 支持断点续传
- 下载完成 → 自动跳转生成页面

**设置页新增「模型管理」tab：**
- 已下载模型列表（大小、下载日期、VRAM 占用参考）
- 下载新模型 / 删除已有模型
- 切换默认使用模型

---

### M4 · 安装体验
优先级：🟡 中（发布前必须完成）

**4-A Pinokio App 定义：**
- 仓库根目录添加 `pinokio.json`（Pinokio 标准格式）
- 定义 install / start / stop 步骤
- 在 Pinokio registry 提交收录

**4-B Windows 一键安装包：**
- `scripts/install.bat`：检查 Python → 建 venv → pip install → 创建桌面快捷方式
- `scripts/start.bat`：激活 venv → 启动服务 → 打开浏览器
- 发布时打包为 `cubify3d-windows.zip`（含脚本 + README）

**4-C Linux 一键安装脚本：**
- `scripts/install.sh`：同上逻辑，兼容 Ubuntu / Debian / RHEL
- 支持 `curl -fsSL https://get.cubify3d.com/install.sh | bash`

**4-D 先决条件检测：**
- 安装脚本自动检测：GPU 驱动版本、CUDA 版本、Python 版本、可用磁盘空间
- 不满足时输出清晰的提示信息（链接到文档）

---

### M5 · 文档完善
优先级：🟡 中（开源必须，影响社区采用率）

- `README.md`：效果截图、功能列表、快速开始（三种安装方式）、系统要求
- `docs/INSTALL.md`：各平台详细安装步骤
- `docs/API.md`：REST API 完整参考（由现有 FastAPI OpenAPI 导出 + 补充说明）
- `docs/MODELS.md`：支持的模型列表、VRAM 要求、质量对比
- `docs/CONTRIBUTING.md`：如何贡献代码、开发环境搭建
- `CHANGELOG.md`：v0.1 变更记录

---

### M6 · 发布前 QA & 清理
优先级：🟡 中（发布质量保障）

- 安全审查：默认 API token 机制、CORS 配置、不暴露内部路径
- `docker-compose.yml` 拆分：
  - `docker-compose.yml`（含 build，开发用，现有）
  - `docker-compose.release.yml`（纯 image，生产用）
- Web UI chunk 优化：主 JS < 500kB，消除 Vite warning
- 全量测试通过（目标：85+ passed，新增 HunYuan3D tests）
- GPU 真机验收：TRELLIS2 + HunYuan3D 各生成 3 个 3D 资产，质量 review

---

## 暂缓 / 重新定位的事项

| 事项 | 原计划 | 新状态 |
|------|--------|--------|
| E15-B server→gen3d 集成 | 🔴 近期 | 🔵 独立文档：作为"如何接入外部后端"的示例，不再是必做 |
| Phase D 多机 Worker | 🟡 中期 | 🔵 v0.2 企业功能 |
| Mac Apple Silicon 支持 | 未规划 | 🔵 v0.2，via ollama 类工具 |
| Launcher GUI（系统托盘）| 未规划 | 🔵 v0.2 |
| Prometheus/Grafana 完整化 | 技术债 | 🔵 v0.2 企业功能 |

---

## 执行顺序

```
M1（品牌基础）→ M2（HunYuan3D）→ M3（Model 管理 UI）
                                              ↓
                          M4（安装体验）← M5（文档）
                                              ↓
                                       M6（QA & 清理）→ v0.1 发布
```

M1 是前置依赖（改名影响所有文件），M2/M3 可并行，M4/M5 可并行，M6 最后。

---

## Notes

- 开发阶段继续用 Docker，安装体验（M4）是发布前工作
- LICENSE 选 Apache 2.0：允许商业使用（吸引企业用户）、允许 fork（扩大社区）、保留归属要求（保护品牌）
- HunYuan3D-2 是 Tencent 2025 年发布的开源模型，生成质量接近商业水平，是重要差异点
- Model 管理 UI（M3）是设计师上手的关键体验，优先级不低于 HunYuan3D
- v0.1 不追求功能完整，追求**体验闭环**：装上 → 下载模型 → 生成 → 看结果，全程流畅
