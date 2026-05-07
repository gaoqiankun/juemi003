# Cubie 模型管理重构 — Manifest schema + Fetcher 抽象 + 单层继承

Date: 2026-05-06
Status: planning
Prerequisite: `.ai/plan/2026-05-06-cubie-structure-polish.md`(V1-V6) 必须先合 main
Branch: 待启动时建(预定 `dev` 切自 main)

## Goal

把 cubie 的"模型 + 依赖"管理从**隐式 hardcoded**(`weight_source ∈ {hf, url, local}` 单字段 + `weight_manager` 内 if-elif 分支 + provider 代码内 hardcoded deps)重构为**显式 Manifest schema + Fetcher 抽象 + 单层继承**。

不自维 model registry。不锁 HuggingFace 仓库布局。Provider 通过 manifest.yaml 描述自身组成,cubie 用 fetcher 多源拉取。

**核心不变量**:
- HF Hub 仍是事实标准下载源(复用 `huggingface_hub` 库),只是不再是唯一形式
- `dep_store` 保留(全局 dep_id 内容寻址),manifest 引用其中实例
- Provider Python 代码不感知下载,只看 working dir 内本地 path

## 范围 / 出范围

### In-scope
- Manifest schema 定义(YAML / JSON 双支持,YAML 默认)
- Manifest 解析器:加载、验证、继承展开
- Fetcher 抽象 + 5 种实现:`HFFilesFetcher`、`HFRepoFetcher`、`URLFetcher`、`GitFetcher`、`LocalFetcher`(`GithubReleaseFetcher`、`OCIFetcher` 留位)
- `weight_manager` 改造:if-elif 替换为 fetcher dispatch
- Provider 接口扩展:每个 provider 暴露 `manifest.yaml`
- 数据库 schema migration:`models` 表加 `manifest_json` 字段(冗余存储展开后 manifest,便于查询)
- 加载流程:启动时 / admin 触发时 → 读 manifest → 展开继承 → fetcher 拉取 → resolve dep_paths → provider 启动
- Dep 共享:同 dep_id 在多个 model 间符号链接复用
- 老 `weight_source` 字段保留至少 1 个版本,作为 BC layer

### Out-of-scope(独立立项 / 后续考虑)
- 自建 manifest registry(只有未来生态扩张才考虑;目前 manifest 跟 provider 代码同 repo 已经够用)
- Lazy pull on first task(D3 拍板:不 lazy)
- 用户级 manifest 编辑 GUI(后续优化)
- OCI artifact / private registry 集成(留 fetcher 接口位,不实现)
- 加密 / 签名 / 完整性扫描(可附加 sha256 字段但不立刻强制)
- Quantization 转换 / 模型转码(完全交给上游)
- v0.2 polish 范围内任何项(P1-P11 完全独立)
- P12 / P13(allocator 锁重构 / mid-load bug)

## 设计决策(D1-D6)

| ID | 决策 |
|---|---|
| **D1** | manifest 位置:**(a) provider 代码同 repo `manifest.yaml` 默认**(`cubie/model/providers/<name>/manifest.yaml`),**(c) DB seed 可覆盖 / 添加新 model**;未来若做 registry,只维护 manifest 索引,不存 weights |
| **D2** | Component **中粒度** — 按语义分组(`weights / tokenizer / vae / extensions / ...`),不细到每文件,不粗到整 repo |
| **D3** | **不 lazy** — 保持 admin 显式触发或启动预热;无首次任务自动 pull |
| **D4** | HF 角色 **(a) 复用 `huggingface_hub` 库**(`hf_hub_download(filename=)` 拉特定 path);继续吃 HF cache 的 commit-sha 锁 + 内容寻址 + 多实例共享 |
| **D5** | 跨 model dep 共享 **(a) `dep_id` 全局引用 + 符号链接**;`dep_store` 已有 dep_id 全局唯一,manifest 引用 dep_id 时 cubie 保证只下一份,symlink 到每 model working dir |
| **D6** | 继承机制:**形态 A 单层**,真实场景是外部用户 fine-tune 衍生(用户 A `extends: trellis2`,只覆盖 main_weights);深度严格 = 1(父若自带 `extends:` 直接报错);`extends` 引用 model id,不是文件路径 |

### D6 子语义
- **D6.1** 解析:加载时一次性展开成完整 manifest(可缓存);不做运行时 prototype chain
- **D6.2** Override:**id-based 整体替换** — 同 id 覆盖整个 component,新 id 追加;不做 deep-merge
- **D6.3** 删除继承项:不预留语法(YAGNI);需要时再加 `removed_components: [id1]`
- **D6.4** 链深度:严格 = 1 层(子→父),父必须是叶子
- **D6.5** 顶层非 components 字段(`inference` 等):整字段替换;子 manifest 写出来就盖,不写就继承

## Manifest schema v1

```yaml
# 字段说明示例(provider 内置)
id: trellis2                      # 必填,全局唯一
provider_type: trellis2           # 必填,Python provider 类映射
display_name: TRELLIS2
version: "2024.10"                # 可选,显示用
extends: <model-id>               # 可选,继承自另一个已注册 model(深度=1)
description: "..."                # 可选
default_enabled: true             # 是否默认启用
default_default: true             # 是否默认 default

components:                       # 必填(extends 时可省略,继承父的)
  - id: main_weights              # 必填,model 内唯一
    source:
      kind: hf_files              # hf_files | hf_repo | url | git | github_release | local | dep_ref
      # kind=hf_files
      repo: microsoft/TRELLIS.2-4B
      revision: main              # commit-sha / branch / tag,可选(默认 main)
      paths: ["*.safetensors", "config.json"]   # glob 模式
      # kind=url
      # url: https://...
      # sha256: "..."              # 强校验(可选但推荐)
      # kind=dep_ref
      # dep_id: birefnet_v1        # 引用 dep_store 已注册 dep,跨 model 共享
    target: weights/              # 必填,model working dir 相对路径
    extract: true                 # 是否解压(tar/zip),默认 false
    optional: false               # 是否可选(下载失败不致命)

inference:                        # 可选,VRAM 估算
  vram_mb: 16000
  weight_vram_mb: 12000
  inference_vram_mb: 4000

dependencies:                     # 可选,引用 dep_store(等价 components 中 kind=dep_ref)
  - dep_id: birefnet_v1
    role: rmbg                    # 在 provider 内部的语义角色
```

### Fetcher Protocol(草案)

```python
class Fetcher(Protocol):
    @classmethod
    def supports(cls, source: Source) -> bool: ...
    
    async def fetch(
        self,
        source: Source,
        target: Path,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> FetchResult: ...
    
    async def estimate_size(self, source: Source) -> int | None: ...

# 实现:
# HFFilesFetcher(huggingface_hub.hf_hub_download)
# HFRepoFetcher(huggingface_hub.snapshot_download,等于现有 HF 行为)
# URLFetcher(httpx + sha256 校验)
# GitFetcher(asyncio.subprocess git clone --depth 1)
# LocalFetcher(filesystem copy / symlink)
# GithubReleaseFetcher(待实现,gh release API + URLFetcher)
# OCIFetcher(留接口,后续接 oras / skopeo)
# DepRefFetcher(特殊 — resolve dep_id → 调对应 fetcher → symlink 到 target)
```

## 阶段执行计划(M1-M7)

每阶段独立 commit + plan 同 commit + pytest/ruff 全绿。共 ~7 commits。预计总工作量 5-10 工作日。

### M1 — Manifest schema + 解析器 + 继承展开
**改动**:
- 新建 `cubie/model/manifest/` 子包:`schema.py`(Pydantic models)、`parser.py`(YAML 加载)、`inheritance.py`(展开)、`__init__.py`(facade)
- 单元测试 `tests/model/test_manifest.py`:多 manifest 解析、继承展开、单层限制、override 语义
- 不接入主流程,纯独立模块

**AC**:
- pytest 新增 ≥15 用例(每条 schema 字段 + 每条 D6 语义)
- ruff 0
- 父 manifest 自带 `extends` 报错验证

### M2 — Fetcher 抽象 + 5 实现
**改动**:
- 新建 `cubie/model/fetcher/` 子包:`base.py`(Protocol)、`hf.py`(2 个)、`url.py`、`git.py`、`local.py`、`dep_ref.py`、`__init__.py`(facade + dispatcher)
- 单元测试 `tests/model/test_fetcher.py`:每 fetcher 独立测,mock `huggingface_hub` / httpx / git 子进程
- 不接入主流程

**AC**:
- 5 个 fetcher 全部跑通基础下载用例
- HF fetcher 验证 cache 复用(下载第二次走 cache,无网络)
- DepRefFetcher 验证 symlink 行为
- ruff 0

### M3 — weight_manager dispatch 改造
**改动**:
- `cubie/model/weight/__init__.py` 内 if-elif 改为 `fetcher.dispatch(source).fetch(...)`
- 老 `weight_source` 字段:保留,运行时翻译成 `Source(kind=...)` 喂给 fetcher
- 现有测试不动,确保行为等价

**AC**:
- pytest 全绿(基线 ≥223 passed)
- 行为等价:旧 weight_source=huggingface 模型下载效果与改造前对比 byte-for-byte 相同
- ruff 0

### M4 — DB schema migration:`manifest_json` 字段
**改动**:
- `cubie/model/store/migrations.py` 加新 migration(向后兼容,字段允许 NULL)
- 启动时 backfill:所有现有 model 行根据当前 `weight_source / model_path / dep` 信息合成 manifest,写入 `manifest_json` 字段
- 新增 `cubie/model/manifest/migration.py`:老字段 → manifest 转换函数
- 测试 `tests/model/test_store_migrations.py` 验证 backfill 正确性

**AC**:
- 旧 SQLite DB 文件升级后,所有 model 行 `manifest_json` 字段非空
- backfill 后的 manifest 加载效果与原老字段一致
- pytest 全绿,新增 migration 测试 ≥3 用例

### M5 — Provider 暴露 `manifest.yaml`
**改动**:
- `cubie/model/providers/{trellis2,hunyuan3d,step1x3d}/manifest.yaml` 各自写好(完整声明 components + inference + dependencies)
- Provider Python 类增加 `classmethod load_manifest()`,默认从同目录 `manifest.yaml` 读
- 启动 backfill 改用 provider manifest(若 DB 有就用 DB,否则用 provider 内置)
- Mock provider 同样暴露 manifest(测试用)

**AC**:
- 3 个 provider manifest 通过 schema 验证
- 启动时 cubie 能从 provider manifest 加载 model(不依赖 DB seed)
- 老 `weight_source` 字段在 manifest 出现时被忽略(manifest 优先)
- pytest 全绿

### M6 — Admin UI 适配(扩展)
**改动**:
- `cubie/api/routers/admin/models/`:加新接口 `POST /api/admin/models/manifest`(上传 manifest YAML / JSON)
- 老 create / update API 保留兼容
- 前端 `web/src/pages/admin/models/`:加 "manifest source" 选项(直接编辑 / 引用上游 / 上传文件)
- 验证下载流程:用户 fine-tune 场景演示:上传 `extends: trellis2` 的 manifest,只填 main_weights URL,触发下载

**AC**:
- E2E 测试:fine-tune 场景从 admin UI 完成
- 老 admin 接口不破
- pytest + frontend build 通过

### M7 — 老字段清理(可选,看时机)
**改动**:
- 至少跑一个 release 周期后,如确认无 caller,删除 `weight_source / model_path / hf_repo_id` 等老字段
- DB schema migration 删除字段
- 代码内移除 BC layer

**AC**:
- 全代码库无 `weight_source` 引用
- DB schema 清洁
- 单独 commit,可单独回滚

## Acceptance Criteria(总)

**功能**:
- [ ] 3 个 provider 通过 manifest 加载,与改造前行为等价
- [ ] 用户 fine-tune 场景(`extends: trellis2`)端到端通过
- [ ] HF 下载继续吃 cache,断网二次下载 0 网络流量
- [ ] dep_id 共享:同 dep 跨 2+ model 时,文件系统只 1 份 + N symlink
- [ ] 老 SQLite DB 平滑升级,无数据丢失

**结构**:
- [ ] `cubie/model/manifest/` `cubie/model/fetcher/` 两个子包
- [ ] 3 个 provider 各有 `manifest.yaml`
- [ ] DB schema 含 `manifest_json` 字段
- [ ] pytest 新增 ≥30 用例,全绿
- [ ] ruff 0

## 风险登记

| 风险 | 缓解 |
|------|------|
| Manifest schema v1 表达力不够,未来要破坏性升级 | schema 加 `manifest_version` 字段,不同版本独立解析器,不强升级 |
| HFFilesFetcher 依赖 `huggingface_hub` 内部 API 不稳定 | pin 库版本;只用公开 API(`hf_hub_download`、`snapshot_download`),不碰内部 |
| 继承展开循环引用(用户写错 `extends: self`) | 解析时检测;父深度限制天然防御 |
| dep_id 共享 symlink 在 Windows 上行为差异 | 当前 cubie 仅 Linux 部署,Windows 不在范围;若未来支持,改 hardlink fallback |
| backfill 逻辑遗漏某 model 老字段 | M4 测试覆盖每个 weight_source kind;迁移后单跑一次"对比新老路径生成结果是否一致"工具 |
| Provider 既存 hardcode dep 列表(`dependencies()` classmethod)与 manifest 重复 | 留一段时间双轨;manifest 优先,classmethod 仅作为生成 manifest 的工具(M5 阶段处理) |
| 用户 fine-tune 后,manifest 引用了已被 cubie 内置删除的父 model | 加载时报清晰错误,提示用户更新 extends 或固化为完整 manifest |

## 决策记录

- 2026-05-06 D1=a+c, D2=中粒度, D3=不 lazy, D4=复用 huggingface_hub, D5=dep_id+symlink, D6=形态 A 单层
- 2026-05-06 跳过形态 B(跨 provider 共享 stack)+ C(模板抽象):3D 视觉生成各家 pipeline 不同,B 收益低;cubie 当前 3 provider,C 过度设计
- 2026-05-06 不自维 registry,未来若做也只维护 manifest 索引(不存 weights),用户自带分发渠道(HF / 内网 HTTP / OCI)
- 2026-05-06 启动时机:V1-V6 polish 落 main 后再启动;不并入 polish 范围

## 历史关联

- 前置:`.ai/plan/2026-05-06-cubie-structure-polish.md`(V1-V6 polish)
- 现状基线:`.ai/snapshot.md`(v0.2 域驱动 + 9 monolith split + 0 C901)
- 老逻辑参考:`cubie/model/weight/__init__.py`(if-elif 分支)、`cubie/model/dep_store/`(已有 dep_id 全局唯一概念)
- 此 plan 是 cubie v0.3 的核心立项
