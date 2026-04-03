# Admin 面板第 11 轮修复（重做）
Date: 2026-03-23
Status: done
Commits: N/A（按 AGENTS.md，本轮不执行 commit）

## Goal
7 项修复：设置页 HF 面板对齐、按钮真正紧凑、Logo 红点、退出按钮位置、保存按钮位置、HF 登录 bug

## Key Decisions
- HF 面板保持“简洁 label + input”结构，不引入字段级卡片边框；仅统一 label 字形与生成引擎字段一致。
- 为保证 HF 双列输入框水平对齐，将“镜像地址提示文字”移出左侧 label，单独放到两列 grid 下方。
- Admin 操作按钮统一走 `size="sm"`，并把 `Button.sm` 真正收紧到 `h-8`，保证视觉高度不超过输入框。
- “保存变更”归属生成引擎区域，移入 generation card 底部。
- HF 登录状态判定以 token 存在为准，`whoami` 失败仅影响用户名展示。
- HF 面板右列改为固定字段布局：访问令牌输入框始终渲染，连接状态统一放到标题右侧标签，避免列内容跳变。

## Changes
- `web/src/pages/settings-page.tsx`
  - HF 面板：`endpoint/token` label 文案样式改为 `font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted`。
  - HF 面板：`endpointHint` 提示从左列 label 内移到双列 grid 下方单独一行，避免撑高左列导致输入框错位。
  - HF 面板按钮（保存镜像地址/连接/断开）统一加 `size="sm"`。
  - HF 面板右列不再按登录态切换为“状态块”；访问令牌输入框改为始终显示，登录态时禁用并清空 value。
  - HF 标题行改为 `flex`，在标题右侧新增连接状态标签：加载中显示灰色 `...`，已连接显示绿色用户名/“Connected”，未连接显示灰色“Not connected”。
  - “保存变更”按钮区块从页面底部独立 section 移入 generation card 内底部，并改为 `size="sm"`。
- `web/src/components/ui/button.tsx`
  - `sm` 尺寸从 `h-9 px-3 text-xs` 调整为 `h-8 rounded-md px-2.5 text-xs`。
- `web/src/pages/api-keys-page.tsx`
  - 创建密钥按钮增加 `size="sm"`（表格内按钮原本已是 sm，保持不变）。
- `web/src/components/layout/admin-shell.tsx`
  - 删除 Logo 状态圆点、`useGen3d` 依赖和 `toneClass` 计算。
  - 删除侧边栏底部退出按钮。
  - 顶栏主题按钮后新增 LogOut 图标按钮（tooltip 使用 `shell.adminAuth.signOut`）。
  - 鉴权页提交按钮加 `size="sm"`。
- `api/server.py`
  - `_resolve_hf_status()` 中 `whoami` 异常分支由 `return False, None` 改为 `return True, None`。
- `tests/test_api.py`
  - 新增 `test_admin_hf_status_keeps_logged_in_when_whoami_unreachable`，覆盖 token 存在但 whoami 网络失败场景。
- `web/src/i18n/en.json` / `web/src/i18n/zh-CN.json`
  - 新增 `settings.hf.connected` 文案，用于 token 输入框 placeholder 与标题状态标签回退文本。

## Notes
- 验收命令：
  - `cd web && npm run build` 通过
  - `.venv/bin/python -m pytest tests -q` 通过（138 passed）
