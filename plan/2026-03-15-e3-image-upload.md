# E3 · 图片上传接口 + Web 页面文件选择
Date / Status: 2026-03-15 / done / Commits: none

## Goal
用户通过 Web 页面直接上传本地图片，不再要求填写外部图片 URL。

## Key Decisions

### 内部 upload:// scheme（核心设计）
- 不用 file:// 绕过 SSRF，而是引入内部 `upload://` scheme：
  - `POST /v1/upload` 保存文件到 `uploads_dir/{upload_id}.{ext}`，返回 `{"upload_id": "...", "url": "upload://{upload_id}"}`
  - `security.py` `validate_image_url` 白名单加 `upload://`（内部可信，直接通过）
  - `PreprocessStage` 新增 `upload://` handler → 读 `uploads_dir/{upload_id}.*`，复用现有 `_read_local_file`
  - DB 里存 `upload://abc123`，短字符串，不存原始文件内容

### 上传端点
- 路由：`POST /v1/upload`，auth 同 `require_bearer_token`
- 接受：`multipart/form-data`，字段名 `file`
- 校验：content-type 必须为 image/jpeg|png|webp|gif；文件大小 ≤ `preprocess_max_image_bytes`
- 存储：`uploads_dir/{upload_id}.{ext}`（upload_id = uuid4 hex，ext 按 content-type 推断）
- 返回：`{"upload_id": str, "url": str}`

### 文件清理
- 暂不自动清理（测试工具可接受），后续可加 TTL 脚本

### Web 页面
- 现有 URL 输入框改为「图片上传」区域：拖拽 + 点击选文件
- 选中后显示缩略图预览，自动触发 `POST /v1/upload`
- 上传完成后将 `url` 填入提交逻辑，用户点「生成」即提交任务
- 保留 URL 输入的选项（折叠/可展开），不完全移除

## Changes
| 文件 | 变更说明 |
|------|---------|
| `config.py` | 新增 `uploads_dir: Path`，默认 `./data/uploads` |
| `security.py` | `validate_image_url` 允许 `upload://` scheme 通过 |
| `stages/preprocess/stage.py` | 构造函数增 `uploads_dir`；`_read_input_bytes` 增 `upload://` 分支 |
| `api/server.py` | 新增 `POST /v1/upload` 端点；启动时创建 `uploads_dir`；PreprocessStage 传入 `uploads_dir` |
| `api/schemas.py` | 新增 upload 响应模型 |
| `static/index.html` | 图片上传区域（拖拽+点击）、缩略图预览、上传进度、保留 URL 输入折叠 |
| `tests/` | 补充 upload 端点测试（正常上传、格式校验、大小限制）和 `upload://` preprocess 测试 |
| `README.md` / `docs/PLAN.md` | 同步 `UPLOADS_DIR` 和 `upload://` 设计说明 |

## Notes
- `uploads_dir` 需在服务启动时创建（`mkdir -p`）
- `upload://` URL 由 Web 页面持有并直接提交任务，但不会作为可下载/可访问的外部资源暴露
- Web 页面上传用 `Authorization: Bearer {token}` 同任务提交
- `POST /v1/upload` 使用手动 multipart 解析，避免额外依赖 `python-multipart`
- `python -m pytest tests -q` 结果：`44 passed`
