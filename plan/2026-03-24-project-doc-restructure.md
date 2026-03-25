# 项目文档重整
Date: 2026-03-24
Status: done

## Goal
项目迭代至 108 个 plan 文件，CLAUDE.md / AGENTS.md 与代码严重脱节，影响 AI Coder 工作效率。
本次进行全面现状审计并重整所有文档。

## Key Decisions
- 归档 plan/2026-03-10 至 2026-03-20 共 50 个文件至 plan/archive/，保留 3/21-3/24 共 58 个
- CLAUDE.md 全量重写：更新测试基线（161）、Provider 状态（全部实现）、前端路由表、技术债清单
- AGENTS.md 全量重写：更新目录结构（补 pagination.py / security.py / artifact_store.py / hooks/）、移除过期 NotImplementedError 说明、补 Toast/路由表/i18n key 数
- 5 个状态写错的 plan 文件（planning→done）修正为 done

## Changes
- `CLAUDE.md`：全量重写
- `AGENTS.md`：全量重写
- `plan/archive/`：新建，归入 50 个历史 plan 文件
- `plan/2026-03-23-admin-actions-colspan-layout.md` 等 5 个：status 修正为 done

## Notes
- 唯一仍为 planning 的历史文件：`plan/2026-03-15-e5-compose-admin-upload-env.md`（deploy.sh 补 ADMIN_TOKEN= 待完成）
- 测试基线 161 passed（原 AGENTS.md 写的是 85，严重过时）
- proof-shots-page.tsx / reference-compare-page.tsx 存在但未挂载路由，已在文档中标注
