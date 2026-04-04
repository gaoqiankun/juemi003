# Dep Weight Source Configuration
Date: 2026-04-05
Status: draft

## Goal

Dep 实例（dep_instances）对标主模型实例（model_definitions）：同一 dep 类型（如 birefnet）
可以有多个权重实例，多个主模型实例可以指向同一 dep 实例（共享），也可以各用不同实例。

添加主模型时，对每个 dep 类型：
- 已有实例 → 让用户从现有实例中选择
- 无实例 / 想新增 → 填 display_name + 权重来源，创建新实例

---

## 数据模型

### dep_instances（新表，替换 dep_cache）

类比 model_definitions，每行是一个具体的 dep 权重实例：

```sql
CREATE TABLE dep_instances (
    id                 TEXT PRIMARY KEY,   -- e.g. "birefnet-v1"（slugify display_name 或自动生成）
    dep_type           TEXT NOT NULL,      -- canonical dep id，e.g. "birefnet"
    hf_repo_id         TEXT NOT NULL,      -- 该 dep_type 的默认 HF repo（参考用）
    display_name       TEXT NOT NULL,      -- 用户命名
    weight_source      TEXT NOT NULL DEFAULT 'huggingface',
    dep_model_path     TEXT,              -- HF repo override / local path / URL
    resolved_path      TEXT,
    download_status    TEXT NOT NULL DEFAULT 'pending',
    download_progress  INTEGER NOT NULL DEFAULT 0,
    download_speed_bps INTEGER NOT NULL DEFAULT 0,
    download_error     TEXT,
    created_at         TEXT DEFAULT (datetime('now'))
)
```

### model_dep_requirements（重构）

主模型实例 → dep 实例的多对多映射：

```sql
CREATE TABLE model_dep_requirements (
    model_id         TEXT NOT NULL REFERENCES model_definitions(id) ON DELETE CASCADE,
    dep_type         TEXT NOT NULL,        -- canonical dep id（用于 provider dep_paths 映射）
    dep_instance_id  TEXT NOT NULL REFERENCES dep_instances(id),
    PRIMARY KEY (model_id, dep_type)
)
```

### 旧数据迁移

`dep_cache` → `dep_instances`：
- `dep_id` 既是 instance id 又是 dep_type（旧系统 1:1）
- `display_name = dep_id`，`weight_source = 'huggingface'`

`model_dep_requirements`（旧: model_id + dep_id）→（新: model_id + dep_type + dep_instance_id）：
- `dep_type = dep_id`，`dep_instance_id = dep_id`（旧 dep_id 直接作为 dep_instance_id）

迁移用 RENAME + CREATE + INSERT + DROP 方式（SQLite 不支持 ALTER COLUMN / DROP COLUMN）。
旧 `dep_cache` 表也用同样方式迁移到 `dep_instances`。

---

## 文件变更

### 1. `storage/dep_store.py`

完整重写，主要变化：

#### `_ensure_schema`

```python
async def _ensure_schema(db):
    # 检测是否存在旧表
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dep_cache'"
    )
    has_dep_cache = cursor.fetchone() is not None

    # 创建新表
    await db.execute("""
        CREATE TABLE IF NOT EXISTS dep_instances (
            id                 TEXT PRIMARY KEY,
            dep_type           TEXT NOT NULL,
            hf_repo_id         TEXT NOT NULL,
            display_name       TEXT NOT NULL,
            weight_source      TEXT NOT NULL DEFAULT 'huggingface',
            dep_model_path     TEXT,
            resolved_path      TEXT,
            download_status    TEXT NOT NULL DEFAULT 'pending',
            download_progress  INTEGER NOT NULL DEFAULT 0,
            download_speed_bps INTEGER NOT NULL DEFAULT 0,
            download_error     TEXT,
            created_at         TEXT DEFAULT (datetime('now'))
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS model_dep_requirements (
            model_id        TEXT NOT NULL REFERENCES model_definitions(id) ON DELETE CASCADE,
            dep_type        TEXT NOT NULL,
            dep_instance_id TEXT NOT NULL REFERENCES dep_instances(id),
            PRIMARY KEY (model_id, dep_type)
        )
    """)

    # 旧数据迁移
    if has_dep_cache:
        await db.execute("""
            INSERT OR IGNORE INTO dep_instances
                (id, dep_type, hf_repo_id, display_name, weight_source,
                 resolved_path, download_status, download_progress,
                 download_speed_bps, download_error)
            SELECT dep_id, dep_id, hf_repo_id, dep_id, 'huggingface',
                   resolved_path, download_status, download_progress,
                   download_speed_bps, download_error
            FROM dep_cache
        """)
        # 旧 model_dep_requirements 可能有旧 schema
        cursor = await db.execute("PRAGMA table_info(model_dep_requirements)")
        mdr_cols = {row[1] for row in await cursor.fetchall()}
        if "dep_instance_id" not in mdr_cols and "dep_id" in mdr_cols:
            await db.execute("""
                INSERT OR IGNORE INTO model_dep_requirements (model_id, dep_type, dep_instance_id)
                SELECT model_id, dep_id, dep_id
                FROM model_dep_requirements
                WHERE dep_id IN (SELECT id FROM dep_instances)
            """)
            # 删旧表（旧 model_dep_requirements 已被新表替换，无法直接 ALTER）
            # 方案：旧行保留在同一张表中（如果 schema 能兼容）或 RENAME
            # 由于新旧 PK 相同，用 INSERT OR IGNORE 去重后旧行自动无效
            # 实际处理：如果 dep_id 列存在但 dep_instance_id 不存在，需要重建表
            await db.execute("ALTER TABLE model_dep_requirements RENAME TO _mdr_old")
            await db.execute("""
                CREATE TABLE model_dep_requirements (
                    model_id        TEXT NOT NULL REFERENCES model_definitions(id) ON DELETE CASCADE,
                    dep_type        TEXT NOT NULL,
                    dep_instance_id TEXT NOT NULL REFERENCES dep_instances(id),
                    PRIMARY KEY (model_id, dep_type)
                )
            """)
            await db.execute("""
                INSERT OR IGNORE INTO model_dep_requirements (model_id, dep_type, dep_instance_id)
                SELECT model_id, dep_id, dep_id FROM _mdr_old
                WHERE dep_id IN (SELECT id FROM dep_instances)
            """)
            await db.execute("DROP TABLE _mdr_old")
        await db.execute("DROP TABLE IF EXISTS dep_cache")
```

#### `DepInstanceStore`（替换 `DepCacheStore`）

```python
class DepInstanceStore(_SQLiteStore):
    async def list_by_dep_type(self, dep_type: str) -> list[dict]:
        """列出某 dep_type 的所有实例，按 created_at 排序。"""

    async def get(self, instance_id: str) -> dict | None:
        """按 instance id 获取。"""

    async def create(
        self,
        instance_id: str,
        dep_type: str,
        hf_repo_id: str,
        display_name: str,
        *,
        weight_source: str = "huggingface",
        dep_model_path: str | None = None,
    ) -> dict:
        """INSERT OR IGNORE，返回行。"""

    async def update_status(self, instance_id: str, status: str) -> dict | None: ...
    async def update_progress(self, instance_id: str, progress: int, speed_bps: int) -> dict | None: ...
    async def update_done(self, instance_id: str, resolved_path: str) -> dict | None: ...
    async def update_error(self, instance_id: str, error: str) -> dict | None: ...

    async def get_all_for_model(self, model_id: str) -> list[dict]:
        """
        JOIN model_dep_requirements ON dep_instance_id = dep_instances.id
        WHERE model_id = ?
        返回含 dep_type 字段的 dep instance 列表。
        """
```

#### `ModelDepRequirementsStore`（精简）

```python
class ModelDepRequirementsStore(_SQLiteStore):
    async def assign(self, model_id: str, dep_type: str, dep_instance_id: str) -> None:
        """INSERT OR REPLACE INTO model_dep_requirements."""

    async def get_assignments_for_model(self, model_id: str) -> list[dict]:
        """返回 [{dep_type, dep_instance_id}, ...]。"""
```

旧 `link` / `get_dep_ids_for_model` 方法删除，调用方一并更新。

---

### 2. `engine/weight_manager.py`

#### 暴露 `get_provider_deps`（模块级函数）

```python
def get_provider_deps(provider_type: str) -> list[ProviderDependency]:
    provider_cls = _get_provider_class(provider_type)
    return _resolve_provider_dependencies(provider_cls)
```

#### `WeightManager.__init__` 依赖注入

`dep_store` 参数类型从 `_DepStoreProtocol` 改为 `_DepInstanceStoreProtocol`（新 Protocol），
`model_dep_requirements_store` 对应新的 `ModelDepRequirementsStore` 接口。

#### `WeightManager.download` 增加 `dep_assignments`

```python
async def download(
    self,
    model_id: str,
    provider_type: str,
    weight_source: str,
    model_path: str,
    dep_assignments: dict[str, dict] | None = None,
) -> str:
```

`dep_assignments` 结构（key = dep_type，value = 指定实例或新实例配置）：
```python
{
    "birefnet": {
        "instance_id": "birefnet-v1"          # 使用现有实例
    },
    "dinov3-vitl16": {
        "new": {                               # 新建实例
            "instance_id": "dinov3-custom",    # 预生成 id
            "display_name": "DINOv3 Custom",
            "weight_source": "local",
            "dep_model_path": "/data/dinov3",
        }
    }
}
```

#### `_download_model_dependencies`

```python
async def _download_model_dependencies(
    self,
    model_id: str,
    provider_type: str,
    dep_assignments: dict[str, dict] | None = None,
) -> None:
    dependencies = get_provider_deps(provider_type)
    assignments = dep_assignments or {}

    for dep in dependencies:
        assignment = assignments.get(dep.dep_type) or {}  # dep.dep_id 即 dep_type

        if "instance_id" in assignment:
            # 使用现有实例，只做 link
            instance_id = assignment["instance_id"]
            # 验证实例存在
            instance = await self._dep_store.get(instance_id)
            if instance is None:
                raise ValueError(f"dep instance not found: {instance_id}")
        else:
            # 新建实例
            new_cfg = assignment.get("new") or {}
            instance_id = str(new_cfg.get("instance_id") or "").strip()
            if not instance_id:
                raise ValueError(f"dep {dep.dep_id}: new instance must have instance_id")
            display_name  = str(new_cfg.get("display_name") or dep.dep_id).strip()
            weight_source = _normalize_weight_source_loose(new_cfg.get("weight_source"))
            dep_model_path = str(new_cfg.get("dep_model_path") or "").strip() or None
            await self._dep_store.create(
                instance_id, dep.dep_id, dep.hf_repo_id, display_name,
                weight_source=weight_source, dep_model_path=dep_model_path,
            )

        await self._model_dep_requirements_store.assign(model_id, dep.dep_id, instance_id)

    # 下载阶段（只下载新建实例，已有实例跳过）
    for dep in dependencies:
        assignment = assignments.get(dep.dep_id) or {}
        if "instance_id" in assignment:
            continue   # 使用现有实例，不重新下载
        new_cfg = assignment.get("new") or {}
        instance_id    = str(new_cfg.get("instance_id") or "").strip()
        weight_source  = _normalize_weight_source_loose(new_cfg.get("weight_source"))
        dep_model_path = str(new_cfg.get("dep_model_path") or "").strip() or None
        try:
            await self._download_dep_once(dep, instance_id, weight_source, dep_model_path)
        except Exception as exc:
            raise RuntimeError(f"dep_{dep.dep_id}: {exc}") from exc
```

注：`dep_assignments` 若为空（{}），对 HunYuan3D（0 deps）无影响；
对有 deps 的 provider 需要有 assignment，否则 `new_cfg` 为空，会 raise。
server.py 在调用前负责补全缺失的 assignment（见 3b）。

#### `_download_dep_once` / `_download_dep`

与上一版相同，只是 lock key 改为 `instance_id`：

```python
async def _download_dep_once(
    self,
    dep: ProviderDependency,
    instance_id: str,
    weight_source: str,
    dep_model_path: str | None,
) -> None:
    dep_lock = self._dep_locks.setdefault(instance_id, asyncio.Lock())
    async with dep_lock:
        existing = await self._dep_store.get(instance_id)
        if existing and existing.get("download_status") == "done":
            return
        await self._dep_store.update_status(instance_id, "downloading")
        try:
            resolved = await self._download_dep(dep, weight_source, dep_model_path, instance_id)
        except Exception as exc:
            await self._dep_store.update_error(instance_id, str(exc))
            raise
        await self._dep_store.update_done(instance_id, resolved)
```

`_download_dep` 三种来源（local / huggingface / url）与上一版一致；
URL 下载目标目录改为 `self._cache_dir / "deps" / _cache_key(instance_id)`。

`_cache_key` 扩展为 `re.sub(r"[^a-zA-Z0-9_\-]", "_", normalized)`。

#### `_resolve_dep_paths`（server.py 中）

```python
assignments = await model_dep_store.get_assignments_for_model(model_id)
for asgn in assignments:
    dep_type    = asgn["dep_type"]
    instance_id = asgn["dep_instance_id"]
    instance    = await dep_instance_store.get(instance_id)
    if instance is None or instance.get("download_status") != "done":
        raise ValueError(f"dep {dep_type} (instance {instance_id}) not ready")
    dep_paths[dep_type] = instance["resolved_path"]
```

---

### 3. `api/server.py`

> ⚠️ 当前 2571 行，超警告线。新增约 60 行，Worker 完成后须在 report 注明最终行数。

#### 新路由：`GET /api/admin/providers/{provider_type}/deps`

返回该 provider 需要的所有 dep 类型 + 各自现有实例列表：

```json
[
  {
    "dep_type": "birefnet",
    "hf_repo_id": "ZhengPeng7/BiRefNet",
    "description": "Background removal (BiRefNet)",
    "instances": [
      {
        "id": "birefnet-v1",
        "display_name": "BiRefNet Official",
        "dep_type": "birefnet",
        "weight_source": "huggingface",
        "dep_model_path": "ZhengPeng7/BiRefNet",
        "download_status": "done",
        "download_progress": 100,
        "resolved_path": "/data/models/birefnet-v1"
      }
    ]
  }
]
```

```python
@app.get("/api/admin/providers/{provider_type}/deps", dependencies=[Depends(require_admin_token)])
async def list_provider_deps(
    provider_type: str,
    app_container: AppContainer = Depends(get_container),
) -> list[dict]:
    from gen3d.engine.weight_manager import get_provider_deps
    dependencies = get_provider_deps(provider_type)
    result = []
    for dep in dependencies:
        instances = await app_container.dep_instance_store.list_by_dep_type(dep.dep_id)
        result.append({
            "dep_type": dep.dep_id,
            "hf_repo_id": dep.hf_repo_id,
            "description": dep.description,
            "instances": instances,
        })
    return result
```

#### `create_model` 接受 `depAssignments` 并补全 + 验证

`depAssignments` 从 payload 提取（key = dep_type）。

**补全逻辑（server.py 中，同步执行）**：
对 provider 的每个 dep_type，如果 `depAssignments` 中没有该 dep_type 的条目，
自动生成一个新实例配置（weight_source = huggingface，dep_model_path = hf_repo_id，
display_name = dep_type，instance_id = `{dep_type}-{model_id}`）。
这样无 dep 的 provider（hunyuan3d）直接跳过，有 dep 的 provider 即使用户未填也有默认值。

**验证逻辑**：
- 若 `instance_id` 指向现有实例：查 dep_instance_store 确认存在
- 若 `new`：
  - weight_source 合法（huggingface / local / url）
  - local：dep_model_path 非空 + 路径存在（同步检查）
  - url：http(s):// 开头 + .zip/.tar.gz 结尾
  - huggingface：dep_model_path 为空（用 hf_repo_id）或 owner/repo 格式
  - instance_id 不与已有实例冲突（INSERT OR IGNORE 可处理，但最好提前检查返回清晰错误）

**传递给下载任务**：
```python
app_container.model_download_tasks[model_id] = asyncio.create_task(
    _run_model_weight_download(
        model_id=model_id,
        provider_type=provider_type,
        weight_source=weight_source,
        model_path=model_path,
        dep_assignments=dep_assignments,   # NEW
    )
)
```

#### `AppContainer` 增加 `dep_instance_store`

替换原 `dep_cache_store`（或并列存在过渡）。

#### `get_model_deps` 端点更新

使用 `dep_instance_store.get_all_for_model(model_id)` 替换旧的 `dep_cache_store.get_all_for_model`。
响应结构与旧版兼容（保留 `dep_id`、`download_status` 等字段，新增 `dep_type`、`instance_id`、`display_name`）。

---

### 4. `web/src/lib/admin-api.ts`

#### 新增接口

```typescript
export interface DepInstance {
  id: string;
  dep_type: string;
  hf_repo_id: string;
  display_name: string;
  weight_source: "huggingface" | "local" | "url";
  dep_model_path?: string;
  download_status: DepDownloadStatus;
  download_progress: number;
  download_speed_bps: number;
  resolved_path?: string;
  download_error?: string;
}

export interface ProviderDepType {
  dep_type: string;
  hf_repo_id: string;
  description: string;
  instances: DepInstance[];
}

export interface DepAssignment {
  instance_id?: string;   // 选择现有实例
  new?: {                 // 新建实例
    instance_id: string;
    display_name: string;
    weight_source: "huggingface" | "local" | "url";
    dep_model_path: string;
  };
}
```

#### 新增 fetch 函数

```typescript
export const fetchProviderDeps = (providerType: string): Promise<ProviderDepType[]> =>
  adminFetch<ProviderDepType[]>(
    `/api/admin/providers/${encodeURIComponent(providerType)}/deps`,
  );
```

#### `RawDepStatus` 兼容扩展

增加可选字段 `instance_id?: string`、`dep_type?: string`、`display_name?: string`，
不影响现有 `normalizeDepStatus`。

---

### 5. `web/src/components/add-model-dialog.tsx`

#### State 扩展

```typescript
const [providerDeps, setProviderDeps] = useState<ProviderDepType[]>([]);
const [providerDepsLoading, setProviderDepsLoading] = useState(false);

// 每个 dep_type 的选择：
// "existing:{instance_id}" → 使用现有实例
// "new" → 新建实例
const [depChoices, setDepChoices] = useState<Record<string, string>>({});

// 新建实例的表单字段，key = dep_type
const [newDepNames,   setNewDepNames]   = useState<Record<string, string>>({});
const [newDepSources, setNewDepSources] = useState<Record<string, WeightSource>>({});
const [newDepPaths,   setNewDepPaths]   = useState<Record<string, Record<WeightSource, string>>>({});
```

#### providerType 变更时加载 deps

```typescript
useEffect(() => {
  // 清除旧 state
  setProviderDeps([]); setDepChoices({});
  setNewDepNames({}); setNewDepSources({}); setNewDepPaths({});
  if (!providerType) return;
  let cancelled = false;
  setProviderDepsLoading(true);
  fetchProviderDeps(providerType)
    .then((deps) => {
      if (cancelled) return;
      setProviderDeps(deps);
      const choices: Record<string, string> = {};
      const names: Record<string, string> = {};
      const sources: Record<string, WeightSource> = {};
      const paths: Record<string, Record<WeightSource, string>> = {};
      for (const dep of deps) {
        if (dep.instances.length > 0) {
          // 默认选第一个现有实例
          choices[dep.dep_type] = `existing:${dep.instances[0].id}`;
        } else {
          // 无实例，默认新建
          choices[dep.dep_type] = "new";
          names[dep.dep_type] = dep.dep_type;
          sources[dep.dep_type] = "huggingface";
          paths[dep.dep_type] = { huggingface: dep.hf_repo_id, local: "", url: "" };
        }
      }
      setDepChoices(choices); setNewDepNames(names);
      setNewDepSources(sources); setNewDepPaths(paths);
    })
    .catch(() => { if (!cancelled) setProviderDeps([]); })
    .finally(() => { if (!cancelled) setProviderDepsLoading(false); });
  return () => { cancelled = true; };
}, [providerType]);
```

#### dep UI 区块

每个 dep_type 一张卡（`rounded-xl border border-outline p-3 grid gap-2`）：

**标题行**：`dep.description || dep.dep_type`（semibold）+ `dep.hf_repo_id`（text-xs）

**选择行**：SelectField，选项为：
- 每个现有实例：`value="existing:{id}"` → label = `{display_name}（{download_status}）`
- 最后一项："+ New instance"（`value="new"`）

当前 choice 为 `existing:xxx` 时：
- 展示被选实例的状态（DepDownloadStatus badge）
- 不展示来源表单

当前 choice 为 `new` 时：
- 展示新建表单：
  - Name InputField（`newDepNames[dep_type]`）→ 对应 display_name
  - 来源行：与主权重一致，SelectField（source）+ InputField（path）

#### validate 增加 dep 校验

对 choice = "new" 的每个 dep：
- display_name 不为空
- weight_source + path 合法（与主模型验证逻辑一致）

#### handleSubmit 构建 `depAssignments`

```typescript
const depAssignments: Record<string, DepAssignment> = {};
for (const dep of providerDeps) {
  const choice = depChoices[dep.dep_type] || "new";
  if (choice.startsWith("existing:")) {
    const instanceId = choice.slice("existing:".length);
    depAssignments[dep.dep_type] = { instance_id: instanceId };
  } else {
    const src  = newDepSources[dep.dep_type] || "huggingface";
    const path = (newDepPaths[dep.dep_type]?.[src] || "").trim();
    const name = (newDepNames[dep.dep_type] || dep.dep_type).trim();
    const instanceId = slugify(name) || `${dep.dep_type}-${Date.now()}`;
    depAssignments[dep.dep_type] = {
      new: { instance_id: instanceId, display_name: name, weight_source: src, dep_model_path: path },
    };
  }
}
await onSubmit({ ..., depAssignments });
```

---

### 6. i18n

删除旧 guidance 三个 key，新增：

```json
// zh-CN
"deps": {
  "sectionTitle": "依赖模型",
  "loading": "正在加载依赖列表...",
  "newInstance": "+ 新建实例",
  "namePlaceholder": "实例名称",
  "nameLabel": "名称",
  "sourceLabel": "来源"
},
"errors": {
  "depNameRequired":  "请输入依赖 {{depType}} 的实例名称。",
  "depHfInvalid":     "依赖 {{depType}} 的 HuggingFace 仓库格式应为 owner/repo。",
  "depLocalRequired": "请输入依赖 {{depType}} 的本地路径。",
  "depUrlInvalid":    "依赖 {{depType}} 的 URL 须以 http:// 或 https:// 开头。"
}
```

---

## 注意事项

1. **`AppContainer.dep_cache_store` → `dep_instance_store`**：
   server.py 中所有 `dep_cache_store` 引用改为 `dep_instance_store`；
   `DepCacheStore` → `DepInstanceStore`；初始化 / 关闭同步更新。

2. **`_build_dep_response_rows`**：调整以使用 dep_instances 字段（`dep_type`、`display_name`、`instance_id`）。

3. **`migrate_dep_cache.py` 脚本**：已过时，添加注释说明该脚本已被 `_ensure_schema` 的自动迁移替代，
   不删除文件（保留历史），但在脚本顶部加 `# DEPRECATED` 注释。

4. **`_cache_key` 正则扩展**：`re.sub(r"[^a-zA-Z0-9_\-]", "_", normalized)`，
   避免 dep instance id 中的特殊字符影响文件系统路径。

5. **`dep_locks` key 改为 `instance_id`**：两个模型共享同一 dep 实例 → 同一把锁 → 不重复下载。
   两个模型用不同实例 → 不同锁 → 各自独立下载。

---

## Acceptance Criteria

### 后端
1. `uv run ruff check .` 无新增问题
2. `uv run python -m pytest tests -q` pass 数 ≥ 163
3. `dep_instances` 表存在，`dep_cache` 表已删除（`PRAGMA table_info` / `sqlite_master` 验证）
4. 旧 `dep_cache` 数据正确迁移到 `dep_instances`（dep_id → id + dep_type，weight_source = 'huggingface'）
5. `GET /api/admin/providers/trellis2/deps` → 3 个 dep_type，每个含 `instances` 数组
6. `GET /api/admin/providers/hunyuan3d/deps` → `[]`
7. 未知 provider_type → `[]`
8. 添加模型，dep 指定 `instance_id`（现有实例）→ 不重新下载，只做 link
9. 添加模型，dep 指定 `new`（local 路径不存在）→ 返回 422
10. `_resolve_dep_paths` 用 `dep_type` → `dep_instance.resolved_path` 正确映射
11. `GET /api/admin/models/{model_id}/deps` 响应兼容旧字段（`dep_id` / `download_status`），新增 `display_name`

### 前端
12. `cd web && npm run build` 零错误
13. `cd web && npm run lint` 无新增问题
14. 选择 trellis2 → deps 区块出现 3 个 dep 卡片
15. 选择 hunyuan3d → 无 deps 区块
16. dep 已有实例 → SelectField 默认选第一个现有实例，不显示新建表单
17. 选择"+ 新建实例"→ 显示 Name + 来源配置表单
18. dep 无实例 → 直接显示新建表单
19. 提交 payload 含 `depAssignments`，结构正确（devtools network 验证）
20. en / zh-CN i18n key 集合一致，旧 guidance key 已删除
