# Add Model Dialog — Dependency Guidance
Date: 2026-04-04
Status: done

## Goal
添加模型对话框缺少依赖说明，用户不知道：
1. 选择 HuggingFace 来源后，模型依赖权重会被自动下载
2. 不同 provider 有不同的依赖（step1x3d 有 4 个 dep，trellis2/hunyuan3d 较少）

## Changes
`web/src/components/add-model-dialog.tsx`：
- 在 weight source 区块下方（error 提示之前）加一个静态说明区块
- 内容：说明主模型权重来源由用户指定；依赖权重由系统在模型首次加载前自动下载（无需手动操作）
- 当 providerType 为 step1x3d 时，补一行提示：Step1X-3D 需要额外依赖（SDXL、BiRefNet 等），首次加载前需确保网络可访问 HuggingFace，或依赖已提前缓存
- i18n：新增文案同步到 `web/src/i18n/en.json` 和 `web/src/i18n/zh-CN.json`

## Acceptance Criteria
1. `cd web && npm run build` 零错误
2. `cd web && npm run lint` 不新增问题
3. 说明区块在 HF/local/url 三种 source 下均可见
4. step1x3d provider 时额外提示可见，其他 provider 时不显示
5. en/zh-CN i18n key 一致
