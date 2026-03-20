# Cubie 3D · Claude 架构师记忆

> 子仓库：`./gen3d/`（独立 git 仓库，本地目录名暂未改动）
> 最后更新：2026-03-20
> **战略转型**：gen3d → Cubie 3D，独立开源项目，任何人可本地部署

---

## 项目定位

**Cubie 3D** 是一个可私有部署的开源 3D 生成服务，目标对标 Meshy / Tripo3D 商业产品水平。
类比 ComfyUI / InvokeAI 在图像生成领域的地位，专注 3D 生成。

- 目标用户：专业设计师、独立开发者、企业私有化部署
- 主平台：Linux / Windows + NVIDIA GPU（CUDA）
- 开发阶段：Docker
- 正式发布：Portable 安装包（主推）/ Pinokio / Docker

---

## 规划日志

- 历史规划在 `plan/`，最新见 2026-03-20 的开源转型总规划

---

## 当前状态（2026-03-20）

- Phase A/B/C 全部完成，测试基线：`python -m pytest tests -q` **85 passed**
- **当前阶段：Cubie 3D 开源转型，v0.1 发布准备**

### v0.1 模块进度

| 模块 | 状态 |
|------|------|
| M1 · 品牌 & 开源化基础 | ✅ 完成（已部署验证） |
| M2 · Admin Panel（5页双主题+i18n） | ✅ 完成（build通过，Playwright验证） |
| M2.5 · 用户侧页面（Generate/History/Viewer/Setup） | ✅ 完成（build通过，Playwright验证） |
| M3 · HunYuan3D Provider | 🔲 待开始 |
| M4 · 安装体验（Pinokio + 脚本）| 🔲 待开始 |
| M5 · 文档完善 | 🔲 待开始 |
| M6 · 发布前 QA & 清理 | 🔲 待开始 |

---

## 关键路径

- `plan/` 中 2026-03-20 的开源转型总规划：v0.1 完整规划
- `docs/PLAN.md`：架构基线
- `AGENTS.md`：给 AI Coder 的速查说明
- 根目录关键文件：`config.py` / `serve.py` / `requirements.txt` / `docker-compose.yml`
- 核心目录：`api/` / `engine/` / `model/` / `stages/` / `storage/` / `observability/` / `tests/`

---

## Provider 状态

| Provider | 状态 |
|---------|------|
| `mock`（MockTrellis2Provider）| ✅ 可用 |
| `real`（Trellis2Provider）| ✅ 可用 |
| `hunyuan3d`（HunYuan3D-2）| 🔲 M2 待实现 |

---

## 暂缓事项

| 事项 | 说明 |
|------|------|
| E15-B 外部后端接入示例 | 转为文档示例，不再是必做 |
| Phase D 多机 Worker | v0.2 企业功能 |
| Mac Apple Silicon | v0.2，via ollama 类工具 |
| Launcher GUI | v0.2 |

---

## 技术债（长期）

- IP 白名单校验：E10 已存 IP，校验逻辑等 nginx 路径稳定后开启
- GPU 细粒度进度 hook：`gpu_ss/gpu_shape/gpu_material` 是语义占位
- GPU scheduler：简单 FIFO，`max_batch + deadline` 调度未实现
- 取消运行中任务：目前只支持 `gpu_queued` 状态

---

## 使用提醒

- 项目已转型为独立开源项目 Cubie 3D，不依赖内部基础设施命名
- 设计调整前先读 `plan/` 中 2026-03-20 的开源转型总规划
- 当前首要任务是 M1（品牌基础），它是其他模块的前置依赖
