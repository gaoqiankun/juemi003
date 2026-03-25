# gen3d Phase B 第二轮：artifact backend 与对外语义收口

Date / Status: 2026-03-11 / done

## Goal

在保留 Phase B 第一轮已完成的 real provider + real preprocess + real local export + mock fallback 基础上，把 artifact 存储与对外语义收口到可生产演进的形态：通过 store 抽象同时支持 local 与 MinIO/S3 兼容对象存储，并让任务详情、`/artifacts`、终态 webhook 在两种 backend 下保持稳定结构与状态语义。

## Key Decisions

- 不推翻现有 API / Engine / Pipeline / Provider / Store 分层；对象存储能力只进入 `storage/artifact_store.py` 与配置装配层
- `uploading` 作为真实阶段进入状态流；local backend 也必须经过同一语义，而不是直接 `exporting -> succeeded`
- 自动化测试默认仍以 local backend 为主；MinIO 行为通过 fake client / isolated unit test 覆盖，不依赖真实 MinIO 环境
- 本轮不宣称真实 GPU 成功生成已完成；若缺少 GPU、权重或对象存储环境，仅实现 fail-fast 与可诊断性

## Changes

- `ServingConfig` 新增 artifact backend / object store 相关配置：`ARTIFACT_STORE_MODE`、`OBJECT_STORE_ENDPOINT`、`OBJECT_STORE_EXTERNAL_ENDPOINT`、`OBJECT_STORE_BUCKET`、`OBJECT_STORE_ACCESS_KEY`、`OBJECT_STORE_SECRET_KEY`、`OBJECT_STORE_REGION`、`OBJECT_STORE_PREFIX`、`OBJECT_STORE_PRESIGN_TTL_SECONDS`
- `api/server.py` 新增 `build_artifact_store()`，明确支持 `local` 与 `minio` 两种 backend，并在 `minio` 模式下对必填配置做 fail-fast 校验
- `storage/artifact_store.py` 从单一本地 mock store 重构为可生产演进的双后端抽象：
- `local` backend：staging -> 本地 finalize -> `file://` URL
- `minio` backend：staging -> S3 compatible upload -> presigned URL
- MinIO 启动初始化会先做 bucket 校验；无真实环境时，自动化测试通过 fake object storage client 覆盖上传与 presign 语义
- `ExportStage` 改为真实使用 `exporting -> uploading -> succeeded` 流程；local backend 不再绕过 `uploading`
- `GET /v1/tasks/{id}`、`GET /v1/tasks/{id}/artifacts`、终态 webhook 统一输出同一套 artifact 结构：
- `type`
- `url`
- `created_at`
- `size_bytes`
- `backend`
- `content_type`
- `expires_at`
- `TaskError` / webhook `error` 统一使用 `failed_stage`，避免 API 与 webhook 诊断字段分叉
- 本轮新增 `mock_failure_stage=uploading`，可直接覆盖上传阶段失败语义
- `requirements.txt` 增加 `boto3`
- `README.md` 更新 local/minio 两种 backend 的前置条件、配置方式、smoke 验证方式和当前未验证边界
- 自动化测试扩展到：
- SSE / 事件历史包含 `uploading`
- local backend 成功任务 artifact 结构一致性
- `uploading` 失败诊断
- MinIO 缺配置 fail-fast
- fake client / fake presign 的 MinIO isolated 单测
- 本轮本地执行 `python -m pytest tests -q`，结果为 `18 passed`

## Notes

- local / minio backend 的切换只通过 `ARTIFACT_STORE_MODE` 进行；provider mode 仍独立由 `PROVIDER_MODE=mock|real` 控制
- local backend 现在不再区分 mock URL 与 real URL；无论 provider 是 mock 还是 real，只要 backend 是 `local`，返回的都是本地 `file://` 语义，artifact 字段结构保持一致
- `failed_stage=uploading` 目前覆盖：
- local finalize 失败
- MinIO 上传失败
- presigned URL 生成失败
- mock 注入上传失败
- 当前环境没有接入真实 MinIO，也没有完成 `real provider + GPU + 权重` 的成功生成实测，因此本轮没有虚报这两项人工验收已完成
- 真实 GPU 成功生成这项验收仍需满足：
- 可见 CUDA GPU
- 可用 TRELLIS2 runtime 与本地模型目录
- 至少一次真实图片成功任务（可配 local 或 minio backend）
