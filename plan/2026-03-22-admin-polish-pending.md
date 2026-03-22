# Admin 面板待处理问题
Date: 2026-03-22
Status: planning

## Goal
上一轮（round 7-10）验收过程中发现的遗留问题，下次会话继续处理。

## 待修复

### 1. HF 登录状态误判（后端 bug）
`api/server.py` 的 `_resolve_hf_status()` 中 `whoami` 网络失败时返回未登录。
国内服务器访问不了 HF API，即使有有效 token（环境变量或 cli login）也显示未连接。
**修复方向**：有 token 即为已登录，`whoami` 只尝试获取用户名，失败时返回已登录但用户名为 None。

### 2. 设置页"保存变更"按钮位置不对
当前在页面最底部，跟 HuggingFace 面板混在一起，用户不知道保存的是什么。
**修复方向**：移到生成引擎卡片内部，HF 面板有自己独立的操作按钮，两个卡片各管各的。

### 3. 退出按钮移到导航栏
当前在侧边栏底部，占空间且排版跟导航项不协调。
**修复方向**：移到右上角导航栏右侧，纯 LogOut 图标按钮 + tooltip（"退出"/"Sign out"），跟语言/主题图标风格统一。侧边栏去掉退出按钮。

### 4. 用户侧退出机制（v0.2）
用户侧 API Key 保存在浏览器里，任何人打开就能用。需要退出/清除 Key 的能力。
优先级低于 Admin 侧，后续版本再加。

## 本次会话已提交的 commits
- `14cb5ba` — round 7: merge dashboard, simplify keys/settings, sign-out, fix bugs
- `1b5f940` — round 8: compact models table, auto-refresh, center headers, relocate status dot
- `6a7d1ca` — round 9: HuggingFace panel, fix DELETE 204, remove redundant UI
- `56b3930` — round 10: unify table alignment, add HF endpoint setting

## 测试基线
- 前端：`npm run build` 通过（Node v24）
- 后端：`python -m pytest tests -q` → 137 passed
