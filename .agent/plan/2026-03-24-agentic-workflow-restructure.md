# Agentic 协作规范落地
Date: 2026-03-24
Status: done

## Goal
参考 agentic_coding.txt，为人和各类 Agent 建立清晰高效的协作规范，解决文档混乱、规则堆叠、无法分层加载的问题。

## Key Decisions

### 三层文档体系
- README.md：人类 onboarding（是什么、怎么跑、目录说明）
- AGENTS.md + CLAUDE.md：Agent 规则（核心约束 + 架构记忆）
- web/AGENTS.md + .claude/rules/：子模块规则（按需加载）

### 前后端规则分离
- 主 AGENTS.md 去掉前端设计系统细节，只保留核心架构规则
- `web/AGENTS.md`：前端专项规则（布局/组件/i18n，~50 行）
- `.claude/rules/frontend.md`：Claude Code 路径触发规则
- `.claude/rules/backend.md`：Python 修改规则

### Skill 化高频流程
- `.claude/skills/new-provider/`：新增 3D Provider 的完整操作清单
- `.claude/skills/ui-polish/`：UI 打磨轮的检查清单和规范

### CLAUDE.md 精简
- 去掉设计系统细节（移入 web/AGENTS.md），保留架构决策的 WHY

## Changes
- `AGENTS.md`：重写，精简至核心规则，添加 Skills 引用
- `web/AGENTS.md`：新建，前端专项规则
- `.claude/rules/frontend.md`：新建
- `.claude/rules/backend.md`：新建
- `.claude/skills/new-provider/SKILL.md`：新建
- `.claude/skills/ui-polish/SKILL.md`：新建
- `CLAUDE.md`：精简，去设计系统细节，补全架构决策表
- `README.md`：重写，清晰的人类 onboarding 入口

## Notes
- 遵循 agentic_coding.txt 核心原则：写规则不写背景故事，写命令不写"注意测试"
- AGENTS.md 从 ~150 行精简到 ~80 行，通过子文件承载细节
