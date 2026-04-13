# Server Split — S1: Extract module-level helpers
Date: 2026-04-13
Status: done

## Summary

把 `api/server.py` 中 lines 1–1272 范围内的 ~50 个 module-level 辅助函数提取到新建的 `api/helpers/` 子模块 9 个主题文件。函数体零修改，纯位置搬迁。server.py 从 **3525 → 2462 行（-1063 行）**，pytest 218 passed 不变。

第一轮 Worker 输出引入了一个模块元类 `_ServerModule` 桥来同步 monkeypatch 目标到 helpers，被 Orchestrator validate 时 REVISE 拒掉；走 quickfix 路径把元类桥拆掉，改为更新 `tests/test_api.py` + `tests/test_vram_inference_estimate_clamp.py` 中的 ~30 处 monkeypatch 路径直接指向 `helpers.*` 模块。最终形态：server.py 顶部干净，无任何元类魔法、无镜像同步、无重复 import。

## Goal

把 `api/server.py` 中 lines 1–1272 范围内的 ~50 个 module-level 辅助函数全部提取到新建的 `api/helpers/` 子模块，按主题分组成 9 个文件。**严格只搬不改**：函数体零修改，仅迁移 + 调整 import 路径。`create_app` 内部一行不动。

这是「server.py 拆分」三 slice 计划的第一步：

- **S1（本 plan）**：搬 helpers，3525 → ~2500 行（-1000）
- **S2（未来）**：闭包提升到 AppContainer / 服务对象
- **S3（未来）**：48 路由提取到 APIRouter 文件

完成后 `api/server.py` 仍是巨型工厂函数，但 helper 噪音消失，下一 slice 视野清晰。

## Non-goals

- **不**修改 `create_app` 内部任何代码（包括闭包、DI、路由、lifespan）
- **不**改任何函数签名（包括下划线前缀的内部 helper）
- **不**重命名函数/参数/变量
- **不**优化、合并、删除 helpers——即使发现重复或可简化也留到后续 plan
- **不**碰 `class AppContainer` / `class SPAStaticFiles`（这俩留在 server.py，分别因 DI 和 SPA 路由耦合）
- **不**改任何 import 别名导出契约（`serve.py` / `tests/test_api.py` / `tests/test_vram_inference_estimate_clamp.py` 现有 import 必须继续工作）

## Design

### 文件分组（9 文件，全部新建在 `api/helpers/`）

| 文件 | 包含 helper（按当前 server.py 中行号顺序） | 估算行数 |
|---|---|---|
| `api/helpers/__init__.py` | 空文件，让 `api/helpers/` 成为 package | 0 |
| `api/helpers/hf.py` | `_ensure_hf_client_available` (165) / `_normalize_hf_endpoint` (173) / `_set_hf_endpoint` (186) / `_current_hf_endpoint` (205) / `_resolve_hf_status` (209) / `_is_hf_repo_id` (565) | ~80 |
| `api/helpers/keys.py` | `_short_key_id` (227) / `_resolve_task_owner` (236) / `_build_user_key_label_map` (249) / `_safe_record_usage` (286) | ~80 |
| `api/helpers/tasks.py` | `_map_task_status` (223) / `_friendly_model_error_message` (265) | ~40 |
| `api/helpers/artifacts.py` | `_extract_artifact_filename` (367) / `_resolve_dev_local_model_path` (376) / `build_artifact_store` (753) / `_artifact_file_name_from_url` (1064) / `_artifact_matches_file_name` (1070) / `_artifact_exists` (1077) / `_merge_preview_artifacts` (1093) / `_render_preview_artifact_on_demand` (1120) / `_dispatch_preview_render` (1175) | ~250 |
| `api/helpers/deps.py` | `_provider_dependency_descriptions` (426) / `_build_dep_response_rows` (430) / `_resolve_dep_paths` (464) / `_normalize_new_dep_config` (511) / `_normalize_single_dep_assignment` (525) / `_normalize_dep_assignments_payload` (551) / `_default_dep_assignment` (573) / `_validate_existing_dep_assignment` (584) / `_validate_new_dep_model_path` (607) / `_validate_new_dep_assignment` (648) / `_prepare_dep_assignments` (703) | ~290 |
| `api/helpers/gpu_device.py` | `_resolve_device_ids` (791) / `_get_gpu_device_info` (816) / `_normalize_persisted_disabled_devices` (930) / `_ordered_disabled_devices` (945) / `_parse_gpu_disabled_devices_update` (952) | ~100 |
| `api/helpers/vram.py` | `_normalize_vram_mb` (830) / `_resolve_total_vram_mb` (842) / `_resolve_weight_vram_mb` (854) / `_detect_device_total_vram_mb` (864) / `_summarize_inference_options` (883) / `_clamp_inference_estimate_mb` (890) | ~120 |
| `api/helpers/runtime.py` | `build_provider` (391) / `_resolve_model_definition_for_runtime` (914) / `build_model_runtime` (971) | ~190 |
| `api/helpers/preflight.py` | `run_real_mode_preflight` (1205) / `validate_runtime_security_config` (1269) | ~80 |

**留在 `api/server.py` 顶部的**（按现状不动）：
- `from __future__ import annotations` + 所有 stdlib / third-party / gen3d.* import
- `class AppContainer` (319) — 闭包/DI 强耦合
- `class SPAStaticFiles` (341) — SPA 路由用，但只是单类，不值得为它单独建文件；可选移动到 `api/helpers/spa_static.py`，**Worker 决定**
- `_logger = structlog.get_logger(...)` 等模块级单例
- `def create_app(...)` 整体（line 1273+）

### Import 重定向

每个新 helper 文件需要：
1. 从原 `api/server.py` 的 import 块中**复制（不删原行）**它实际用到的 import
2. helper 内部相互调用时改成跨模块 import（例如 `_resolve_dep_paths` 用 `_normalize_new_dep_config`，二者同文件直接调用即可）
3. helper 跨文件调用时显式 import（例如 `runtime.py` 的 `build_model_runtime` 调用 `vram.py` 的 `_clamp_inference_estimate_mb`）

`api/server.py` 的 import 块在 helper 全部搬走后清理：
- 删掉只被搬走的 helper 用的 import（例如 HF 相关的 `_HF_*` 常量、`huggingface_hub` import 移到 `helpers/hf.py`）
- 保留 `create_app` 内部仍然要用的 import（`Depends`, `FastAPI`, `Response`, `Request`, schemas, stores, engines 等）
- **新增**从 helpers 的批量 import：
  ```python
  from gen3d.api.helpers.hf import (
      _ensure_hf_client_available,
      _resolve_hf_status,
      ...
  )
  from gen3d.api.helpers.deps import (
      _build_dep_response_rows,
      _prepare_dep_assignments,
      ...
  )
  # ... etc for all 8 helper files
  ```

### 向后兼容契约（关键）

外部 importer 现状：

| 来源 | import |
|---|---|
| `serve.py:16` | `from gen3d.api.server import create_app, run_real_mode_preflight` |
| `tests/test_api.py:26` | `from gen3d.api.server import create_app, run_real_mode_preflight` |
| `tests/test_vram_inference_estimate_clamp.py:15` | `from gen3d.api.server import _clamp_inference_estimate_mb` |

`create_app` 仍在 server.py 不影响。`run_real_mode_preflight` 和 `_clamp_inference_estimate_mb` 搬到 helpers 后，**必须在 `api/server.py` 顶部 re-export 保持名字可见**：

```python
# 在 api/server.py 顶部 import 块之后、函数定义之前
from gen3d.api.helpers.preflight import run_real_mode_preflight  # noqa: F401  re-export
from gen3d.api.helpers.vram import _clamp_inference_estimate_mb  # noqa: F401  re-export
```

`# noqa: F401` 抑制 ruff 的"unused import"告警。**不要**改测试文件的 import 路径——这个 plan 只动 server.py 自己。

### 模块级常量

server.py 顶部有些 `_HF_*` / `_DEFAULT_DEVICE_TOTAL_VRAM_MB` 之类的常量，Worker 在搬迁时按"哪个 helper 用就跟着搬到哪"原则处理；如果跨多个 helper 文件用，复制到各文件（不创建 `helpers/constants.py` 这种垃圾桶）。

### 操作顺序建议（Worker 自由调整）

1. 先建 `api/helpers/__init__.py`
2. 按主题 9 文件**逐个**搬：复制 helper 函数体 + 它用到的 import → 删原 server.py 中的定义 → 在 server.py import 块新增 from helpers.xxx import → 跑 `pytest tests/test_api.py -q` 局部回归
3. 全部搬完后跑 full pytest + ruff + 行数核查

## Acceptance Criteria

- [ ] 新建 `api/helpers/` 目录，含 `__init__.py` + 9 个 `.py` 文件（按上表分组）
- [ ] `api/server.py` 中 lines 1–1272 范围的 ~50 个 helper 全部从原位置删除（class `AppContainer` / `SPAStaticFiles` 除外）
- [ ] `api/server.py` 顶部 re-export `run_real_mode_preflight` 和 `_clamp_inference_estimate_mb`，带 `# noqa: F401`
- [ ] `api/server.py` 的 import 块清理掉只被搬走 helper 用的 import；新增 from helpers.* 的批量 import
- [ ] 每个新 helper 文件 ≤ 300 行（参考估算，最长的 `deps.py` ~290 也在阈值内）
- [ ] `api/server.py` 最终行数 **≤ 2600**（基线 3525，目标减 ≥ 925 行）
- [ ] `uv run python -m pytest tests -q` 仍 218 passed
- [ ] `uv run ruff check api/ tests/` 受触及范围无新增告警（baseline diff 比对）
- [ ] `serve.py` 无修改、`tests/test_api.py` 无修改、`tests/test_vram_inference_estimate_clamp.py` 无修改
- [ ] `from gen3d.api.server import create_app, run_real_mode_preflight, _clamp_inference_estimate_mb` 三者均可 import（手动 smoke：`uv run python -c "from gen3d.api.server import create_app, run_real_mode_preflight, _clamp_inference_estimate_mb; print('ok')"`)

### 交付形态

- [ ] 单 commit `refactor: api/server.py S1 — extract module-level helpers to api/helpers/`
- [ ] commit 包含 plan 文件（status: done）
- [ ] commit 含 1 新目录 `api/helpers/` 含 10 个文件 + `api/server.py` 修改

## Files to touch

**新建：**
- `api/helpers/__init__.py`
- `api/helpers/hf.py`
- `api/helpers/keys.py`
- `api/helpers/tasks.py`
- `api/helpers/artifacts.py`
- `api/helpers/deps.py`
- `api/helpers/gpu_device.py`
- `api/helpers/vram.py`
- `api/helpers/runtime.py`
- `api/helpers/preflight.py`

**修改：**
- `api/server.py`（减 ~1000 行 + import 块重排 + 2 行 re-export）

**不应改动：**
- `serve.py`
- `tests/`（任何文件）
- `engine/`、`stages/`、`storage/`、`model/` 等其它 package
- `web/`

## Key Decisions

1. **为什么 9 个文件而不是更少**：每个文件单一职责（HF / deps / keys / tasks / artifacts / GPU device / VRAM / runtime / preflight），符合 AGENTS.md "single responsibility per file"；最大文件 ~290 行也低于 300 行阈值
2. **为什么 `tasks.py` 只有 2 个 helper 也独立成文件**：`_map_task_status` 和 `_friendly_model_error_message` 都是任务结果格式化，未来 S2/S3 重构 task 路由时这个文件会增长；现在塞进 `keys.py` 反而会让职责混乱
3. **为什么 `AppContainer` / `SPAStaticFiles` 留在 server.py**：`AppContainer` 被 DI provider `get_container` 和所有路由强引用，迁出会引入循环 import 风险；`SPAStaticFiles` 是单类、和 SPA 路由强耦合，等 S3 拆 SPA 路由时一起搬
4. **为什么对 `_clamp_inference_estimate_mb` re-export 而非改测试**：测试文件的 import 是公开契约，refactor 不应破坏 importer；用 `# noqa: F401` re-export 是标准 Python 兼容性手法
5. **为什么不允许任何函数体修改**：S1 的核心价值是"零行为变更的纯搬迁"，pytest 218 passed 不变是最强的回归证据；任何"顺手改"都会污染这个证据
6. **为什么 9 文件不放进 `helpers/__init__.py` re-export**：避免 `from gen3d.api.helpers import _foo` 这种"helpers 包就是个大命名空间"的反模式；强制 `from gen3d.api.helpers.hf import _foo` 让调用点暴露真实归属

## Notes

- Worker 必须在 report 里列出每个新 helper 文件的实际行数 + server.py 最终行数，便于核对 acceptance
- Worker 如果遇到某个 helper 的所属归类有疑问（例如 `_is_hf_repo_id` 该归 hf 还是 deps），按本 plan 表格执行；如果表格遗漏，归到最相关的文件并在 report 里 surface
- Worker **不要**自作主张拆出 `helpers/constants.py` / `helpers/types.py` 这种通用桶——常量和类型跟着用它的函数走
- 如果某 helper 在搬迁后发现需要从被搬走的另一个 helper import（跨文件依赖），这是正常的；按需加 from import
- Worker **不要**修改 `serve.py` / `tests/`，发现兼容性问题立即停下来在 report 里 surface 给 Orchestrator

## Changes

**新建 `api/helpers/` 包（10 文件）：**
- `__init__.py` (0)
- `hf.py` (97) — 6 个 HF 助手 + `_is_hf_repo_id`
- `keys.py` (45) — 4 个 API key 助手
- `tasks.py` (38) — `_map_task_status` + `_friendly_model_error_message`
- `artifacts.py` (220) — 9 个 artifact / preview render 助手
- `deps.py` (295) — 11 个 provider deps 助手
- `gpu_device.py` (77) — 5 个 GPU 设备解析助手
- `vram.py` (90) — 6 个 VRAM 估算 / 钳制助手
- `runtime.py` (160) — `build_provider` + `build_model_runtime` + `_resolve_model_definition_for_runtime`
- `preflight.py` (77) — `run_real_mode_preflight` + `validate_runtime_security_config`

**`api/server.py` (3525 → 2462, -1063 行)：**
- 删除 lines 1–1272 范围内的 ~50 个 module-level helper 定义（除 `class AppContainer` / `class SPAStaticFiles`）
- 从 helpers 模块 from-import 它们到 server.py 顶部
- 顶部 re-export `run_real_mode_preflight` + `_clamp_inference_estimate_mb`，带 `# noqa: F401`
- 删除原 HF try/except 重复 import（helpers/hf.py 自己有）
- 删除 `huggingface_hub` / 三个 Provider / `build_boto3_object_storage_client` / `build_provider` 等不再被 server.py 直接使用的 import
- 删除 `import sys` + `import types`（仅元类用过）
- 路由 `login_hf` / `logout_hf` 中 `_hf_login(...)` / `_hf_logout(...)` 改为 `_hf_helpers._hf_login(...)` / `_hf_helpers._hf_logout(...)`，让 monkeypatch 通过 helper 模块属性查找生效

**`tests/test_api.py`（quickfix 阶段更新）：**
- 顶部新增 `from gen3d.api.helpers import artifacts as artifacts_helpers, hf as hf_helpers, runtime as runtime_helpers`
- 19 处 `monkeypatch.setattr(server_module, "_hf_*"/"Trellis2Provider"/"Hunyuan3DProvider"/"Step1X3DProvider"/"build_provider"/"build_boto3_object_storage_client", ...)` → 改为各自的真实归属 helper 模块
- 9 处 `server_module.build_provider(...)` 直接调用 → `runtime_helpers.build_provider(...)`
- 9 处 `server_module._preview_rendering` / `_preview_render_tasks` 直接访问 → `artifacts_helpers.*`
- `server_module.Trellis2Provider` 等类引用 → `runtime_helpers.Trellis2Provider`

**`tests/test_vram_inference_estimate_clamp.py`（quickfix 阶段更新）：**
- `from gen3d.api import server as server_module` → `from gen3d.api.helpers import vram as vram_helpers`
- `monkeypatch.setattr(server_module, "_logger", ...)` → `monkeypatch.setattr(vram_helpers, "_logger", ...)`

## Key Decisions

1. **9 文件分组**：单一职责 + 全部 ≤ 300 行
2. **元类桥被 REVISE 拒**（quickfix 阶段）：第一轮 Worker 为了不改 tests，引入了 `class _ServerModule(types.ModuleType)` 拦截 `__setattr__` 把 server.py 里的符号镜像到 helpers/*。Orchestrator validate 时认为这是 load-bearing 黑魔法，会让 S2/S3 持续累积技术债，决定 REVISE
3. **正确做法是改 monkeypatch 路径**：tests 里的 `monkeypatch.setattr(server_module, "_hf_login", ...)` 是测试**实现细节**，不是公开契约。改为指向 `hf_helpers._hf_login` 是机械替换、零认知负担的标准做法
4. **plan「不改 tests」规则的本意**是保护 import contract，过度收紧到了 monkeypatch 目标——quickfix 阶段显式放宽
5. **`_hf_helpers._hf_login(...)` 调用而非 `from helpers.hf import _hf_login`**：路由必须通过模块属性查找拿到 `_hf_login`，这样 monkeypatch 替换 `helpers.hf._hf_login` 对路由生效；如果改用 `from-import`，Python 会在 import 时就 bind 局部名字，monkeypatch 失效
6. **`AppContainer` / `SPAStaticFiles` 留原位**：闭包/SPA 强耦合，等 S3
7. **re-export 而非改测试 import 路径**：`from gen3d.api.server import _clamp_inference_estimate_mb` 是公开契约，re-export + `# noqa: F401` 保住

## Validate 结果

- pytest: **218 passed**（baseline 不变）
- ruff `api/server.py`: 5 errors，全部 pre-existing（C901 create_app/create_model/update_settings + F841 require_key_manager_token/require_task_viewer_token），**0 新增**
- server.py 行数: 3525 → 2462（-1063）
- 每个 helper 文件 ≤ 300（最大 deps.py 295）
- smoke import: `from gen3d.api.server import create_app, run_real_mode_preflight, _clamp_inference_estimate_mb` ✓
- `serve.py` 未修改 ✓

## Known Tech Debt

- `api/server.py` 仍 2462 行远超 AGENTS.md 500 行建议：S2 闭包提升 + S3 路由提取后才能砍到目标 ~400 行
- `class AppContainer` 还在 server.py，被所有路由强引用，要等 S2 才能搬
