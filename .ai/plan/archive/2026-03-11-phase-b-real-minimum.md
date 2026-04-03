# gen3d Phase B 第一轮：真实单机单卡最小闭环

Date: 2026-03-11
Status: done
Full spec: `docs/PLAN.md`
Build guide: `AGENTS.md`

## Goal

在保留 Phase A mock 能力的前提下，把 gen3d 推进到单机单卡上的真实 3D 生成最小闭环：真实图片输入、真实 preprocess、真实 TRELLIS2 provider、真实 GLB 本地导出，以及成功/失败任务的稳定诊断语义。

## Key Decisions

- 不推翻现有 API / Engine / Pipeline / Stage / Provider / Store 分层；真实链路通过 provider / stage 内部实现切换接入
- mock 继续作为默认安全模式，自动化测试仍跑 mock；real 模式通过显式配置开启，不做静默降级
- real 模式对缺少 GPU、缺少权重、依赖缺失采用 fail-fast，优先保证可诊断性
- preprocess 升级为真实下载 / 解码 / 归一化，同时支持本地测试可用的 `data:` / `file://` 输入，避免自动化测试依赖外网
- 本轮只做单机单卡、单任务最小闭环；多卡、多机、复杂取消、复杂 webhook、对象存储仍保持 deferred

## Changes

- `PreprocessStage` 从占位逻辑升级为真实输入处理：支持 `http(s)://` 下载、`file://` 本地文件、`data:` 内嵌图片与现有本地路径，并完成 Pillow 解码、EXIF 方向纠正、RGBA -> RGB 归一化
- 保持 provider 抽象不变，在 `model/trellis2/provider.py` 内新增 `Trellis2Provider`，并保留 `MockTrellis2Provider`
- `ServingConfig` 新增 `PROVIDER_MODE` / `MODEL_PROVIDER` / `MODEL_PATH` / preprocess timeout 与 max-bytes 等配置项，`mock` 仍为默认模式
- `api/server.py` 新增 provider 选择逻辑：`mock` 模式走原有 MockProvider，`real` 模式走 `Trellis2Provider.from_pretrained()`，不支持的 provider/mode 直接启动失败
- `Trellis2Provider` 对缺少本地权重目录、缺少 `torch`、缺少 `trellis2`、没有可见 CUDA GPU 做 fail-fast；不做静默降级
- `ExportStage` 从单纯 mock 占位导出升级为同时支持真实 provider `export_glb()`；provider 导出错误会保留到 `failed` / `failed_stage`
- `ArtifactStore` 补齐本地 artifact 元数据：`path` / `created_at` / `size_bytes`；real 模式返回 `file://` URL，mock 模式继续返回 `mock://` URL
- `ArtifactPayload` 对外暴露 `path` / `createdAt` / `sizeBytes`，便于本地 artifact 查询
- 自动化测试把外部 `https://example.com/*.png` 假输入替换为内嵌 `data:` PNG，确保真实 preprocess 路径在无外网环境下仍被覆盖
- 新增测试：非法图片输入会在 `preprocessing` 阶段失败；real mode 在缺少本地模型路径时会 fail-fast
- 更新 `README.md`：补充 mock/real 共存模式、real mode 前置条件、启动方式、手动 smoke、fail-fast 语义和 deferred 边界
- `requirements.txt` 新增 `Pillow`，`requirements-worker.txt` 补充 real mode 依赖说明
- 本轮本地执行 `python -m pytest tests -q`，结果为 `13 passed`

## Notes

- 当前环境已确认缺少 `torch`、`trellis2`，且未确认可用 CUDA GPU / 本地 TRELLIS2 权重目录；因此本轮没有虚报“真实推理已本机验证成功”
- 为了跑通新的 preprocess 路径，本轮已在当前环境安装 `Pillow`
- 当前 real mode 的最强保证是：
- 配置入口明确
- 环境不满足时启动 fail-fast 且错误可诊断
- API / 状态流 / SSE / webhook / artifact 查询语义与 mock 模式保持一致
- 当前机器未完成的人工验证项：
- 使用真实 `MODEL_PATH` 启动 `PROVIDER_MODE=real`
- 提交真实图片并完成一次 TRELLIS2 推理
- 生成真实 GLB 本地文件并通过 `/artifacts` 观察到真实 `file://` 元数据
- 刻意留到 Phase B 第二轮以后的事项：
- 经 TRELLIS2 官方 runtime 实测校准的细粒度 GPU 阶段进度回调
- 多卡数据并行与更复杂的 GPU 调度
- 真实对象存储（MinIO / presigned URL）
- 运行中复杂取消、webhook 重试与更完整的生产化治理
