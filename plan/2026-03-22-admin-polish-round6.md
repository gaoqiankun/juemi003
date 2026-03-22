# Admin 面板第六轮打磨：Settings 实质化 + 模型访问控制 + 默认 Provider 动态化
Date: 2026-03-22
Status: done
Commits: N/A（按仓库 AGENTS 约束，本次未执行 git commit）

## Goal
1. Settings 热更新：PATCH 后引擎实例变量立即生效
2. Settings 移除不可运行时修改的项（存储区块、最大并行任务数）
3. 默认 Provider 选项从模型表动态获取，去掉硬编码
4. 引擎提交任务时检查模型 is_enabled，禁用模型拒绝请求
5. 模型加载错误友好化

## Key Decisions
- Settings 热更新采用「保存 DB + 同步更新运行实例」双写：
  - `TokenRateLimiter.update_limits()` 动态更新并发/每小时请求限制；
  - `AsyncGen3DEngine.update_queue_capacity()` 动态更新队列容量阈值。
- 模型运行时状态调研结论：
  - 后端已有运行时状态能力（`ModelRegistry.get_state`），并可读取错误对象（新增 `get_error`）；
  - 因此模型页状态展示采用真实 `runtimeState`，并在 error 状态展示后端友好错误信息。
- Settings 中部署级字段不进入运行时配置：
  - 移除 `storage` 区块；
  - 移除 `maxParallelJobs`（由硬件决定）。
- 默认 Provider 选项不再硬编码 i18n key，改为从模型表动态生成 `value=id`、`label=display_name`。
- 模型禁用校验放在 `/v1/tasks` 提交入口，保证 API 直调也受控；仅对 model_store 中明确 `is_enabled=False` 的模型拒绝，未知模型保持向后兼容。

## Changes
- 运行时热更新能力
  - `security.py`
    - `TokenRateLimiter` 新增 `update_limits(max_concurrent, max_requests_per_hour)` 与只读属性。
  - `engine/async_engine.py`
    - 新增 `update_queue_capacity(queue_max_size)`。
  - `api/server.py`
    - `AppContainer` 增加 `rate_limiter` 引用；
    - `PATCH /api/admin/settings` 在 `settings_store.set_many()` 后立即调用运行时 setter，实现无需重启生效；
    - 增加请求参数校验（整型/范围）。
- Settings 实质化与动态 Provider
  - `api/server.py`
    - `GET /api/admin/settings` 移除 storage 区块与 maxParallelJobs；
    - defaultProvider options 改为从 `model_store.list_models()` 动态构造（`label` + `value`）。
  - `web/src/data/admin-mocks.ts`
    - `SettingOption` 支持 `label`（不再强制 `labelKey`）。
  - `web/src/pages/settings-page.tsx`
    - select 选项渲染支持 `labelKey` 或 `label`。
- 模型访问控制
  - `api/server.py`
    - `/v1/tasks` 提交前校验目标模型在 model_store 中若明确禁用则返回 422：`该模型已被管理员禁用`；
    - 未在 model_store 中定义的模型保持兼容，不阻断。
- 模型加载错误友好化
  - `engine/model_registry.py`
    - 新增 `get_error(model_name)`。
  - `api/server.py`
    - `GET /api/admin/models` 增加 `error_message` 字段；
    - 对 error 状态做友好文案映射：
      - 鉴权错误 → 配置 Token 提示；
      - 网络超时/连接错误；
      - 磁盘不足；
      - GPU OOM；
      - 路径不存在；
      - 其他返回原始错误。
  - `web/src/lib/admin-api.ts`、`web/src/hooks/use-models-data.ts`、`web/src/pages/models-page.tsx`
    - 前端接收并展示 `error_message`（仅 runtimeState=error 时显示）。
- 测试新增（`tests/test_api.py`）
  - 禁用模型提交被拒绝；
  - 未注册模型仍可提交（向后兼容）；
  - settings 返回动态 provider options 且不含 storage/maxParallelJobs；
  - settings PATCH 后立即影响限流与队列容量；
  - 模型加载失败时返回友好错误信息。

## Notes
- 验证结果：
  - `.venv/bin/python -m pytest tests -q` → `135 passed`
  - `cd web && npm run build`（Node v24.14.0）→ 通过，TypeScript 无错误
