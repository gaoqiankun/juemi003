# Docker 部署配置遗留问题排查
Date: 2026-03-23
Status: done
Commits: N/A（按 AGENTS.md，本轮不执行 commit）

## Goal
检查 Docker 部署相关配置（`docker-compose.yml`、`docker/Dockerfile`、`.env/.env.example`、`config.py`、`serve.py`），定位无用、过时、或不一致项，并给出修复方向。

## Key Decisions
- 以“容器运行时实际生效”为判断标准：`docker-compose.yml` 传入的变量 + `ServingConfig`（`config.py`）读取链路 + `serve.py -> create_app()` 启动链路。
- 对“后端未直接读取但由底层运行时/驱动消费”的变量（如 NVIDIA/HF cache 变量）不直接判定为错误，但标记为“需注释澄清”。
- 本文只做审计，不改代码和配置。

## Changes
- 完成 6 个目标文件逐项核对，并补充必要交叉验证（`api/server.py` 读取点、provider 模型路径解析逻辑）。
- 输出 5 个分类下的遗留问题清单（含文件与行号、影响、建议）。

## Findings

### 1) 环境变量一致性

| 问题 | 文件与行号 | 为什么是问题 | 建议修复方向 |
|---|---|---|---|
| `ALLOWED_CALLBACK_DOMAINS` 默认值不一致（高） | `docker-compose.yml:38`，`config.py:130-133`，`.env.example:9` | Compose 默认给空字符串（`${...:-}`），但该字段是复杂类型（tuple）；空字符串会触发 `pydantic_settings` 解析错误，导致服务启动失败。`.env.example` 使用 `[]`，与 compose 默认不一致。 | 统一为 JSON 风格默认值：compose 改成 `ALLOWED_CALLBACK_DOMAINS: ${ALLOWED_CALLBACK_DOMAINS:-[]}`；并在注释中明确该变量必须是 JSON 数组字符串。 |
| `HF_TOKEN` 在模板里存在但运行链路未接入（中） | `.env.example:5`，`docker-compose.yml:16-42`，`config.py:147-152` | `.env.example` 暴露了 `HF_TOKEN`，但 compose 未传入容器，`ServingConfig` 也无该字段；用户在 `.env` 填写后不会生效。 | 二选一：1）在 compose 中显式透传 `HF_TOKEN` 并在启动流程消费；2）从 `.env.example` 删除，改为仅通过 Admin HF 登录流程管理 token。 |
| 后端可配置项未在 compose 暴露（中） | `config.py:92-126`，`api/server.py:665-682`，`docker-compose.yml:16-42` | 后端支持 `GPU_DEVICE_IDS`、`QUEUE_MAX_SIZE`、`WEBHOOK_TIMEOUT_SECONDS`、`WEBHOOK_MAX_RETRIES`、`TASK_TIMEOUT_SECONDS` 等运行参数，但 compose 未透传，Docker 部署无法通过 `.env` 覆盖。 | 在 compose `environment` 增加这些变量透传（带安全默认值），并在 `.env.example` 补齐。 |
| 6 个运行时变量后端无直接读取（低，文档一致性） | `docker-compose.yml:22-25,41-42`，`config.py`（无对应 alias） | `HOME/HF_HOME/XDG_CACHE_HOME/TRITON_CACHE_DIR/NVIDIA_*` 不经 `ServingConfig`，属于第三方库/容器运行时变量；当前没有注释解释“为何后端代码里找不到读取点”。 | 保留变量，但在 compose 注释中明确“由 huggingface_hub / triton / nvidia runtime 消费，非应用层读取”。 |

### 2) 卷挂载有效性

| 问题 | 文件与行号 | 为什么是问题 | 建议修复方向 |
|---|---|---|---|
| `MODEL_DIR` 挂载在默认配置下基本不生效（中） | `docker-compose.yml:21,45`，`model/trellis2/provider.py:340-357` | 默认 `MODEL_PATH` 是 HuggingFace Repo ID（`microsoft/TRELLIS.2-4B`），provider 会走远程模型分支，不读取 `/models/trellis2`；该挂载仅在手动把 `MODEL_PATH` 设为本地路径时才生效。 | 明确策略并统一默认值：要么默认 `MODEL_PATH=/models/trellis2`（配套本地模型卷），要么删除该挂载并在文档里强调使用 HF 缓存目录。 |
| `minio` 数据未持久化（高） | `docker-compose.yml:53-61` | `minio` 写入 `/data`，但未声明 `volumes`；容器重建会丢桶和对象数据。 | 给 `minio` 增加持久卷（如 `${MINIO_DIR:-./data/minio}:/data`），并在 `.env.example` 增加 `MINIO_DIR`。 |

### 3) 端口 / 服务配置

| 问题 | 文件与行号 | 为什么是问题 | 建议修复方向 |
|---|---|---|---|
| healthcheck 使用 `/health` 仅探活，不探就绪（中） | `docker-compose.yml:47`，`api/server.py:811-827` | `/health` 始终返回 `ok`，不会反映引擎/模型是否 ready；部署层可能过早判定“健康”。 | healthcheck 改为 `/readiness`（或 `/ready`），并按真实启动耗时调整 `start_period`。 |

补充核对：端口映射与监听一致（`docker-compose.yml:15` 对应 `config.py:16`、`serve.py:72-76`），该项未发现不一致。

### 4) 构建参数（Build Args / Dockerfile）

| 问题 | 文件与行号 | 为什么是问题 | 建议修复方向 |
|---|---|---|---|
| `NODE_IMAGE` 构建参数未在 compose 透传（低） | `docker/Dockerfile:2`，`docker-compose.yml:11-12` | Dockerfile 有 `ARG NODE_IMAGE`，compose 仅传 `TRELLIS2_IMAGE`；前端构建基镜像无法通过 `.env` 控制。 | 若需要可配置化，compose `build.args` 增加 `NODE_IMAGE`；若不需要，删除该 ARG 以减少歧义。 |
| `MODEL_PATH` 默认值在 Dockerfile 与 Compose 不一致（中） | `docker/Dockerfile:49-52`，`docker-compose.yml:21` | Dockerfile 默认本地路径 `/models/trellis2`，compose 默认 HF Repo ID；两个默认策略冲突，增加运维理解成本。 | 统一单一默认策略（本地模型卷或 HF 下载），并同步 `.env.example` 与文档。 |

### 5) `.env` / `.env.example` 与敏感信息

| 问题 | 文件与行号 | 为什么是问题 | 建议修复方向 |
|---|---|---|---|
| 审计时无 `.env` 实例文件（信息缺口） | 仓库根目录（无该文件） | 只能基于 `.env.example` 与 compose 推断，无法确认线上/本地真实部署值是否偏离。 | 建议新增 `.env.audit.example`（脱敏）或在部署文档给出“必填变量检查清单”。 |
| `.env.example` 与 compose 变量集不一致（中） | `.env.example:1-14`，`docker-compose.yml:12,30-37` | compose 依赖 `TRELLIS2_IMAGE`、`OBJECT_STORE_*`，但 `.env.example` 未提供；反之 `.env.example` 有 `HF_TOKEN`，compose 未使用。 | 对齐变量集合：补齐 compose 依赖项，移除/接入 `HF_TOKEN`，并按“必填/可选”分类。 |
| 对象存储默认凭据硬编码为弱口令（高） | `docker-compose.yml:33-34,57-58` | `minioadmin/minioadmin` 作为默认 AK/SK 与 root 凭据，易被误用于生产。 | 生产配置去掉弱默认值（改为必填）；至少在 compose 中用显式占位符并在启动前校验。 |

## Notes
- 本次是纯审计任务，未修改业务代码。
- 关键高优问题建议先处理顺序：  
  1) `ALLOWED_CALLBACK_DOMAINS` 默认值导致潜在启动失败；  
  2) MinIO 无持久卷；  
  3) 默认对象存储弱凭据。  
