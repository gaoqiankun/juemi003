# gen3d pyenv 环境切换
Date / Status: 2026-03-11 / done

## Goal

把 `gen3d` 的本地 Python 环境管理从仓库内 `.venv` 说明切到用户现有的 `pyenv` / `pyenv-virtualenv` 工作流，避免继续维护一套单独的虚拟环境约定。

## Key Decisions

- 沿用工作区现有习惯：仓库内通过 `.python-version` 固定到命名环境，而不是要求每个仓库自建 `.venv`
- 当前机器上已经有 Python `3.12.7`，且现有 `.venv` 也是在 `3.12.7` 下跑通测试，因此 `gen3d` 本次固定到 `hey3d_gen3d`
- 不重写历史 Phase A 日志；环境切换单独记录为新 plan，避免混淆实现阶段与后续工程化调整

## Changes

- 新增 `.python-version`，内容为 `hey3d_gen3d`
- 更新 `README.md`：安装、启动、测试、smoke 验证均改为 `pyenv` / `pyenv-virtualenv` 流程，测试命令改为 `python -m pytest`
- 更新 `AGENTS.md`：本地启动章节改为 `pyenv` 工作流，并把 Python 版本说明同步到当前实际使用的 `3.12.7`

## Notes

- 这次只切换环境管理方式，不修改服务运行逻辑
- 如果本机尚未创建 `hey3d_gen3d`，需要执行一次 `pyenv virtualenv 3.12.7 hey3d_gen3d`
