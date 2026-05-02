# Backend Architecture Audit · 2026-05

> **目的**：在做任何重构前，完整记录现有后端代码组织的结构性问题。本文档为 v0.2 重构系列的诊断基线，所有分阶段重构 plan 引用此文。
>
> **范围**：自有 Python 源码（不含 `Hunyuan3D-2/`、各 provider 的 `pipeline/` `vendor/` `ext/`）。
>
> **方法**：文件尺寸扫描 + 概念散落映射 + import 耦合分析 + 命名一致性审查 + 测试镜像审查。

---

## 1. 现状概览

```
gen3d/
├── api/                # server.py 2550L (49 routes), schemas.py, helpers/(10 文件)
├── engine/             # 12 文件平铺
├── stages/             # preprocess/, gpu/, export/ 子目录
├── storage/            # 17 文件平铺（task_store_*, artifact_*, model_store, dep_store, ...）
├── model/              # base.py + 3 个 provider 子目录
├── observability/      # logging.py, metrics.py
├── tests/              # 22 文件平铺（test_api.py 6212L）
├── scripts/            # 3 个 migrate_*.py
├── docker/  docs/  design/  data/
├── config.py           # 顶层 loose
├── security.py         # 顶层 loose
├── pagination.py       # 顶层 loose
└── serve.py            # 顶层 loose
```

包根：`gen3d`（目录名即包名，pyproject `name = "cubie"` 仅 metadata）。
测试基线：220 passed。

---

## 2. 五大结构性问题

### 问题 1 — 顶层 loose 文件无归属

| 文件 | 行数 | 实质 | 应属 |
|------|------|------|------|
| `config.py` | 223 | Pydantic Settings | `core/` |
| `security.py` | 157 | rate limiter + URL/IP safety + image-url validator | 应拆：rate limit + URL safety 入 `core/`；Bearer token / API key 业务侧入 `auth/` |
| `pagination.py` | 23 | cursor pagination util | `core/` |
| `serve.py` | 87 | uvicorn CLI 入口 | `core/` 或保留顶层（CLI entry 惯例） |

无 `core/` 包收容这些设施层模块。

### 问题 2 — `engine/` 内 12 文件混三种 prefix-flat 风格

| 风格 | 文件 | 应为子包 |
|------|------|----------|
| `async_engine_*` | `async_engine.py` (437) + `_eta.py` (119) + `_events.py` (103) + `_webhook.py` (161) | `task/async/` |
| `model_*` | `model_registry.py` (429) + `model_scheduler.py` (321) + `model_worker.py` (518) | `model/` |
| `vram_*` | `vram_allocator.py` (1026) + `vram_probe.py` (52) | `vram/` |
| 散件 | `pipeline.py` (455) + `weight_manager.py` (836) + `sequence.py` (208) | 各归域 |

= 假装分组的扁平命名，import 仍是 12 个平级 module。命名风格上 `async_engine.py` 和 `async_engine_eta.py` 看起来是父子，实际是兄弟，误导。

### 问题 3 — `storage/` 17 文件同病

| prefix | 数量 | 应为子包 |
|--------|------|----------|
| `task_store_*` | `task_store.py` + `_analytics.py` + `_codec.py` + `_mutations.py` + `_queries.py` + `_schema.py` = 6 文件 | `task/store/` |
| `artifact_*` | `artifact_store.py` + `_local_backend.py` + `_minio_backend.py` + `_manifest.py` + `_types.py` + `_utils.py` = 6 文件 | `artifact/` |
| 单件 store | `api_key_store.py` (379) / `dep_store.py` (458) / `model_store.py` (719) / `settings_store.py` (107) | 各归域 |
| 客户端 | `object_storage_client.py` (156) | `artifact/` (S3 客户端，artifact 后端依赖) |

命名 convention 不一致：`task_store_queries.py`（用 `_store_` 前缀）vs `artifact_local_backend.py`（用 `artifact_` 前缀）。

### 问题 4 — 核心概念跨多顶层包散落（最致命）

| 概念 | 散落文件 | 跨包数 |
|------|----------|--------|
| **VRAM** | `engine/vram_allocator.py` `engine/vram_probe.py` `engine/model_registry.py` `engine/model_worker.py` `engine/pipeline.py` `stages/gpu/stage.py` `storage/model_store.py` `storage/settings_store.py` `api/helpers/vram.py` `api/server.py` `api/schemas.py` | **11 文件 / 4 顶层包** |
| **Model 生命周期** | `engine/model_registry.py` `engine/model_scheduler.py` `engine/model_worker.py` `engine/weight_manager.py` `storage/model_store.py` `storage/dep_store.py` `model/base.py` `api/helpers/runtime.py` `api/helpers/deps.py` + 3 provider 目录 | **11+ 文件 / 4 顶层包** |
| **Task** | `engine/async_engine*.py` (4) + `engine/pipeline.py` + `engine/sequence.py` + `storage/task_store*.py` (6) | **12 文件 / 2 顶层包** |
| **HF 集成** | `api/helpers/hf.py` `config.py` `engine/weight_manager.py` `storage/dep_store.py` `storage/model_store.py` `model/base.py` 3 provider + 3 scripts/migrate_* | **13 文件 / 5 顶层包** |
| **Auth** | `storage/api_key_store.py` `security.py`（顶层）`api/helpers/keys.py` | **3 文件 / 3 位置** |

= 一次特性变更必穿 3-4 个顶层目录。

### 问题 5 — 错配与命名误导

- `model/` 子目录只放 provider，model **生命周期管理**却在 `engine/` — 概念边界错位
- `model/base.py` (Provider Protocol) 和 `engine/model_registry/scheduler/worker` 应同域，被人为分割
- `api/helpers/runtime.py` 名字"runtime"，实际只构造 `ModelRuntime`（model 域），名字误导
- `engine/model_*` 与 `storage/model_store.py` 命名同根，意图不同（lifecycle vs persistence），易混淆
- `tests/` 平铺 22 文件镜像 monolith；`test_api.py` 6212L 是后端结构散乱的镜像

---

## 3. 实际 Import 耦合（关键 cross-cutting 边）

```
storage/task_store_* ──→ engine.sequence       # 5 文件依赖
stages/* ─────────────→ engine.sequence        # 4 文件依赖
stages/gpu/stage ─────→ engine.model_registry  # GPU stage 直依 lifecycle
stages/gpu/stage ─────→ engine.vram_allocator  # GPU stage 直依 VRAM
api/server ───────────→ engine + storage + stages + model + security + observability
```

**关键观察**：`engine.sequence`（`RequestSequence` 数据类）实际是 task 域核心数据，被 storage/stages/engine 三层共用——其物理位置在 `engine/` 是错的，应在 `task/`（域驱动）或 `core/`（如视为通用）。

**潜在循环依赖风险点**（重构时要避免）：
- `model/` 含 worker，`vram/` 含 allocator 持有 worker 引用 → 通过 Protocol（`ModelWorkerInterface`）解耦，已在用
- `task/pipeline` 调 `model/registry` → 单向，OK
- `stage/` 用 `model/` 与 `vram/` → 单向，OK

---

## 4. 三个重构方向对比

| | A. 域驱动 (推荐) | B. 强化分层 (保守) | C. 混合 (折中) |
|---|---|---|---|
| **思路** | 按业务概念组织，跨技术分层 | 保 `api/engine/storage/stages/model`，prefix → 子包 | 顶层抽 `core/` + 大概念，子包化局部 |
| **VRAM 收敛** | ✅ `vram/` 顶层包 | ❌ 仍跨 engine/storage/api | ✅ `vram/` 顶层包 |
| **Task 收敛** | ✅ `task/` 顶层包 | ❌ 仍跨 engine/storage | ⚠️ 部分 |
| **Model 收敛** | ✅ `model/` 含 lifecycle + provider + storage | ❌ 仍跨 engine/storage/model | ⚠️ 部分 |
| **import 改动量** | 大（200+ 处） | 中（80+ 处） | 中（120+ 处） |
| **风险** | 高（循环依赖排查） | 低（机械移动） | 中 |
| **彻底度** | 高 | 低 | 中 |
| **后续 v0.2 路线兼容** | 直接对齐域 | 还要再做一次 | 部分对齐 |

**决议**：走 **A（域驱动）**。理由：B/C 都是治标，3 个月后还要再做一次；当前 commit 历史干净 + 测试 220 通过，是最佳手术窗口。

---

## 5. 目标结构（A 方案草案）

```
gen3d/
├── core/         # config, pagination, security_net (URL/IP/rate-limit), serve, observability
│   ├── config.py
│   ├── pagination.py
│   ├── netsafety.py        # 自 security.py 拆出 URL/IP validation + rate limiter
│   ├── serve.py
│   └── observability/      # logging.py, metrics.py
├── api/          # server, schemas, helpers/, routes/(future)
├── task/         # task 域全收
│   ├── __init__.py         # 空包标记
│   ├── engine.py           # 自 engine/async_engine.py；不使用 async/ 子包，因 async 是 Python 保留字
│   ├── eta.py              # 自 engine/async_engine_eta.py
│   ├── events.py           # 自 engine/async_engine_events.py
│   ├── webhook.py          # 自 engine/async_engine_webhook.py
│   ├── pipeline.py         # 自 engine/pipeline.py
│   ├── sequence.py         # 自 engine/sequence.py
│   └── store/              # 自 storage/task_store_*
│       ├── __init__.py     # 自 storage/task_store.py，含 TaskStore 主类
│       ├── schema.py
│       ├── codec.py
│       ├── mutations.py
│       ├── queries.py
│       └── analytics.py
├── model/        # model 域全收（lifecycle + provider + storage）
│   ├── base.py             # 自 model/base.py（Provider Protocol）
│   ├── registry.py         # 自 engine/model_registry.py
│   ├── scheduler.py        # 自 engine/model_scheduler.py
│   ├── worker.py           # 自 engine/model_worker.py
│   ├── runtime.py          # 自 api/helpers/runtime.py（ModelRuntime 构造）
│   ├── weight/             # 自 engine/weight_manager.py 拆分（HF/URL/Local）
│   ├── store.py            # 自 storage/model_store.py
│   ├── dep_store.py        # 自 storage/dep_store.py
│   └── providers/          # 自 model/{trellis2, hunyuan3d, step1x3d}/
├── vram/         # VRAM 域全收
│   ├── allocator.py        # 自 engine/vram_allocator.py
│   ├── probe.py            # 自 engine/vram_probe.py
│   ├── helpers.py          # 自 api/helpers/vram.py（clamp + detect）
│   └── (measurements 字段保留 model/store.py，按数据归属)
├── stage/        # 自 stages/
│   ├── base.py
│   ├── preprocess/
│   ├── gpu/
│   └── export/
├── artifact/     # 自 storage/artifact_*
│   ├── store.py
│   ├── manifest.py
│   ├── types.py
│   ├── utils.py
│   ├── object_client.py    # 自 storage/object_storage_client.py
│   └── backends/
│       ├── local.py
│       └── minio.py
├── auth/         # 自 storage/api_key_store + api/helpers/keys + security.py 业务半部
│   ├── api_key_store.py
│   ├── helpers.py
│   └── bearer.py           # 自 api/helpers/security.py（如存在）+ Bearer 部分
├── settings/     # 自 storage/settings_store.py
│   └── store.py
└── tests/        # 镜像新结构
    ├── core/
    ├── task/
    ├── model/
    ├── vram/
    ├── stage/
    ├── artifact/
    ├── auth/
    └── api/
```

---

## 6. 分阶段执行计划

每阶段独立 plan + commit + test pass，分支管理（`dev` 切自 `main`，结束 squash 回）。

| 阶段 | 内容 | 风险 | 测试影响 |
|------|------|------|----------|
| **0** | 建 `core/`，迁入 `config/pagination/security/serve/observability` | 低 | 全文件 import 变更 |
| **1** | 建 `task/`，搬 `engine/async_engine_*` `engine/pipeline` `engine/sequence` `storage/task_store_*` | 中 | task 测试 + pipeline 测试受影响 |
| **2** | 建 `vram/`，搬 `engine/vram_*` `api/helpers/vram` | 低 | vram 测试受影响 |
| **3** | 建/扩 `model/`，搬 `engine/model_*` `engine/weight_manager` `storage/model_store` `storage/dep_store` `api/helpers/runtime/deps`，将 `model/{trellis2,hunyuan3d,step1x3d}` 移到 `model/providers/` | 高 | 多测试受影响，循环依赖风险点 |
| **4** | 建 `artifact/` `auth/` `settings/`，搬对应 storage 文件 | 低 | 对应测试受影响 |
| **5** | `stages/` → `stage/`（rename + 测试镜像） | 低 | stage 测试受影响 |
| **6** | tests/ 子目录镜像新结构（`tests/<domain>/`） | 低 | conftest 路径调整 |
| **7** | 收尾：grep 残留 `gen3d.engine` `gen3d.storage` 旧路径，ruff/pytest 全跑 | — | 全面 |

**重要约束**：
- 此次只做**目录结构调整 + import 路径更新**，不动文件内部代码逻辑
- 模块级重构（如拆分 `vram_allocator.py` 1026L 为 4 文件、拆分 `weight_manager.py` 836L）放到 v0.2 第二轮，每个独立 plan
- `api/server.py` 2550L monolith 不在本轮范围（v0.2 router 重构独立处理）
- 每阶段必须保持 `pytest -q` 全绿（基线 220 passed）

---

## 7. 决策记录

- **2026-05-01** 用户确认：走 A（域驱动），分 7 阶段，先做目录结构布置，模块级重构后续单独处理
- **本文档定位**：v0.2 重构系列的总诊断 + 总目标，不替代各阶段 plan，但所有 plan 引用此文
