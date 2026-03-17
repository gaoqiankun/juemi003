export function renderGeneratePage(ctx) {
  const {
    view,
    currentTask,
    upload,
    hasToken,
    canCancel,
    settingsReadyTone,
    helpers,
  } = ctx;
  const {
    escapeHtml,
    formatStage,
    formatTaskStatus,
    formatTime,
    buildStatusBadge,
    buildLogFeed,
    getTaskShortId,
  } = helpers;

  const statusToneClass = upload.statusTone || "info";
  const heroHint = `
    <div class="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/4 px-3 py-2 text-sm text-slate-300">
      <i data-lucide="gallery-horizontal-end" class="h-4 w-4 text-orange-300"></i>
      <span>历史任务在</span>
      <a class="font-semibold text-white hover:text-orange-200" href="#/gallery">图库查看</a>
    </div>
  `;

  if (view === "uploading") {
    return `
      <section class="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <div class="glass-panel-strong rounded-[34px] p-6 md:p-8">
          <div class="muted-label">Generate</div>
          <h1 class="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white md:text-5xl">上传已接管，马上进入生成流水线。</h1>
          <p class="mt-4 max-w-2xl text-base leading-7 text-slate-300 md:text-lg">
            当前隐藏上传区，避免重复提交。上传完成后会自动创建任务并切入实时进度视图。
          </p>
          <div class="mt-8 rounded-[28px] border border-white/10 bg-white/4 p-5 md:p-6">
            <div class="flex items-center justify-between gap-3 text-sm text-slate-300">
              <span>${escapeHtml(upload.name || "输入图片")}</span>
              <span>${Math.max(0, Math.min(100, Number(upload.uploadProgress) || 0))}%</span>
            </div>
            <div class="progress-track mt-4">
              <div class="progress-bar" style="width:${Math.max(0, Math.min(100, Number(upload.uploadProgress) || 0))}%"></div>
            </div>
            <div class="form-status ${statusToneClass} mt-4">${escapeHtml(upload.statusMessage || "正在上传图片…")}</div>
          </div>
        </div>
        <aside class="glass-panel rounded-[30px] p-5 md:p-6">
          <div class="thumbnail-frame">
            ${upload.previewDataUrl
              ? `<img src="${escapeHtml(upload.previewDataUrl)}" alt="上传预览">`
              : `<div class="thumbnail-placeholder"><div class="flex flex-col items-center gap-3 px-6 text-center"><i data-lucide="image-plus" class="h-10 w-10"></i><div><div class="text-sm font-medium text-white">等待图片读入</div><div class="mt-1 text-xs text-slate-400">本地预览会在这里出现</div></div></div></div>`}
            <div class="thumbnail-overlay">上传中 · ${escapeHtml(upload.name || "image")}</div>
          </div>
          <div class="mt-5 grid gap-3 text-sm text-slate-300">
            <div class="meta-card">
              <span class="muted-label">Connection</span>
              <strong>${settingsReadyTone === "ready" ? "服务可达" : hasToken ? "等待 /ready 确认" : "请先配置 API Key"}</strong>
            </div>
            <div class="meta-card">
              <span class="muted-label">Pipeline</span>
              <strong>Upload -> Create Task -> SSE</strong>
            </div>
          </div>
        </aside>
      </section>
    `;
  }

  if (view === "processing") {
    const progress = Math.max(0, Math.min(100, Number(currentTask?.progress) || 0));
    const queueMeta = currentTask?.queuePosition != null
      ? `队列位置 ${currentTask.queuePosition}`
      : currentTask?.estimatedWaitSeconds != null
        ? `预计等待 ${currentTask.estimatedWaitSeconds}s`
        : "等待实时进度推送";
    return `
      <section class="grid gap-6">
        <div class="flex flex-wrap items-center justify-between gap-4">
          ${heroHint}
          <div class="flex items-center gap-3 text-sm text-slate-400">
            <span class="status-dot ${canCancel ? "ready" : "pending"}"></span>
            <span>${canCancel ? "当前阶段允许取消" : "当前阶段不可取消"}</span>
          </div>
        </div>
        <div class="glass-panel-strong rounded-[36px] p-6 md:p-8 lg:p-10">
          <div class="flex flex-wrap items-start justify-between gap-5">
            <div>
              <div class="muted-label">Processing</div>
              <h1 class="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white md:text-5xl">${escapeHtml(formatStage(currentTask?.currentStage || currentTask?.status || "queued"))}</h1>
              <p class="mt-4 max-w-3xl text-base leading-7 text-slate-300 md:text-lg">
                任务 ${escapeHtml(getTaskShortId(currentTask?.taskId))} 正在运行。状态机会持续用 SSE / 轮询同步后端进度与日志。
              </p>
            </div>
            <div class="rounded-[28px] border border-white/10 bg-white/4 px-5 py-4 text-right">
              <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Progress</div>
              <div class="mt-2 text-4xl font-semibold tracking-[-0.04em] text-white md:text-5xl">${progress}%</div>
              <div class="mt-2 text-sm text-slate-400">${escapeHtml(queueMeta)}</div>
            </div>
          </div>

          <div class="mt-8 grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
            <div class="rounded-[30px] border border-white/10 bg-white/4 p-5 md:p-6">
              <div class="flex items-center justify-between gap-3">
                ${buildStatusBadge(currentTask)}
                <span class="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">${escapeHtml(currentTask?.transport || "connecting")}</span>
              </div>
              <div class="progress-track mt-6">
                <div class="progress-bar" style="width:${progress}%"></div>
              </div>
              <div class="mt-4 grid gap-4 md:grid-cols-3">
                <div class="meta-card">
                  <span class="muted-label">Task ID</span>
                  <strong>${escapeHtml(currentTask?.taskId || "-")}</strong>
                </div>
                <div class="meta-card">
                  <span class="muted-label">Created</span>
                  <strong>${escapeHtml(formatTime(currentTask?.createdAt))}</strong>
                </div>
                <div class="meta-card">
                  <span class="muted-label">Status</span>
                  <strong>${escapeHtml(formatTaskStatus(currentTask?.status))}</strong>
                </div>
              </div>
              <div class="mt-5 flex flex-wrap gap-3">
                <button data-action="cancel-current-task" type="button" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium" ${canCancel ? "" : "disabled"}>
                  <i data-lucide="ban" class="h-4 w-4"></i>
                  ${currentTask?.pendingCancel ? "取消中…" : "取消任务"}
                </button>
                <a href="#/gallery" class="pill-button inline-flex items-center gap-2 rounded-full border border-white/10 bg-white px-4 py-2.5 text-sm font-semibold text-slate-950">
                  <i data-lucide="gallery-horizontal-end" class="h-4 w-4"></i>
                  查看图库
                </a>
              </div>
            </div>
            <div class="rounded-[30px] border border-white/10 bg-white/4 p-5 md:p-6">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <div class="muted-label">Live Logs</div>
                  <div class="mt-1 text-sm text-slate-400">最近 30 条任务事件，持续实时更新。</div>
                </div>
                <span class="text-sm text-slate-400">${currentTask?.events?.length || 0} 条</span>
              </div>
              <div class="log-feed mt-5">
                ${buildLogFeed(currentTask?.events || [], "等待第一条实时日志…")}
              </div>
            </div>
          </div>
        </div>
      </section>
    `;
  }

  if (view === "completed") {
    const downloadUrl = currentTask?.resolvedArtifactUrl || currentTask?.rawArtifactUrl || "";
    return `
      <section class="grid gap-6">
        <div class="flex flex-wrap items-center justify-between gap-4">
          ${heroHint}
          <div class="flex items-center gap-3 text-sm text-slate-400">
            <span class="status-dot ready"></span>
            <span>Three.js 查看器已切入完成态</span>
          </div>
        </div>
        <div class="glass-panel-strong rounded-[36px] p-5 md:p-7 lg:p-8">
          <div class="flex flex-wrap items-start justify-between gap-5">
            <div>
              <div class="muted-label">Completed</div>
              <h1 class="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white md:text-5xl">模型已生成，主屏直接预览。</h1>
              <p class="mt-4 max-w-3xl text-base leading-7 text-slate-300 md:text-lg">
                任务 ${escapeHtml(getTaskShortId(currentTask?.taskId))} 已完成。新任务会在这里自动替换，历史记录统一沉淀到图库。
              </p>
            </div>
            ${buildStatusBadge(currentTask)}
          </div>
          <div class="mt-8 grid gap-6 lg:grid-cols-[1.18fr_0.82fr]">
            <div class="viewer-stage h-[440px] md:h-[560px]">
              <div id="generate-viewer" class="h-full w-full"></div>
            </div>
            <div class="grid gap-4 self-start">
              <div class="meta-card">
                <span class="muted-label">Artifact</span>
                <strong>${downloadUrl ? "GLB 已就绪" : "等待 artifact URL"}</strong>
              </div>
              <div class="meta-card">
                <span class="muted-label">Created</span>
                <strong>${escapeHtml(formatTime(currentTask?.createdAt))}</strong>
              </div>
              <div class="meta-card">
                <span class="muted-label">Updated</span>
                <strong>${escapeHtml(formatTime(currentTask?.updatedAt || currentTask?.lastSeenAt))}</strong>
              </div>
              <div class="rounded-[28px] border border-white/10 bg-white/4 p-5">
                <div class="text-sm leading-7 text-slate-300">${escapeHtml(currentTask?.note || "产物地址已归一化，新创建任务与历史任务共用同一套 URL 解析逻辑。")}</div>
              </div>
              <div class="flex flex-wrap gap-3 pt-2">
                <a href="${escapeHtml(downloadUrl || "#")}" ${downloadUrl ? 'download="model.glb" target="_blank" rel="noopener noreferrer"' : ''} class="pill-button inline-flex items-center gap-2 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-slate-950 ${downloadUrl ? "" : "pointer-events-none opacity-50"}">
                  <i data-lucide="download" class="h-4 w-4"></i>
                  下载模型
                </a>
                <a href="#/gallery" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-slate-200">
                  <i data-lucide="gallery-horizontal-end" class="h-4 w-4"></i>
                  查看图库
                </a>
                <button data-action="reset-generate-flow" type="button" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-slate-200">
                  <i data-lucide="rotate-ccw" class="h-4 w-4"></i>
                  再生成一个
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>
    `;
  }

  if (view === "failed") {
    const title = currentTask?.status === "cancelled" ? "任务已取消" : "本次生成未完成。";
    const copy = currentTask?.error?.message
      || currentTask?.note
      || (currentTask?.status === "cancelled" ? "后端已确认任务取消。你可以重新提交同一张图，或返回 idle 重新上传。" : "后端返回了失败状态，请检查日志后重试。");
    return `
      <section class="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <div class="glass-panel-strong rounded-[34px] p-6 md:p-8">
          <div class="muted-label">Failed</div>
          <h1 class="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white md:text-5xl">${escapeHtml(title)}</h1>
          <p class="mt-4 max-w-2xl text-base leading-7 text-slate-300 md:text-lg">${escapeHtml(copy)}</p>
          <div class="mt-6 rounded-[26px] border border-rose-400/18 bg-rose-500/10 p-5 text-sm leading-7 text-rose-100">
            <div><strong class="text-white">Task ID</strong> · ${escapeHtml(currentTask?.taskId || "-")}</div>
            <div class="mt-2"><strong class="text-white">Stage</strong> · ${escapeHtml(formatStage(currentTask?.currentStage || currentTask?.status || "failed"))}</div>
            <div class="mt-2"><strong class="text-white">Last Update</strong> · ${escapeHtml(formatTime(currentTask?.updatedAt || currentTask?.lastSeenAt))}</div>
          </div>
          <div class="mt-6 flex flex-wrap gap-3">
            <button data-action="retry-current-task" type="button" class="pill-button inline-flex items-center gap-2 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-slate-950">
              <i data-lucide="rotate-cw" class="h-4 w-4"></i>
              重试任务
            </button>
            <button data-action="reset-generate-flow" type="button" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-slate-200">
              <i data-lucide="image-up" class="h-4 w-4"></i>
              重新上传
            </button>
            <a href="#/gallery" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-slate-200">
              <i data-lucide="gallery-horizontal-end" class="h-4 w-4"></i>
              查看图库
            </a>
          </div>
        </div>
        <aside class="glass-panel rounded-[30px] p-5 md:p-6">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="muted-label">Recent Logs</div>
              <div class="mt-1 text-sm text-slate-400">失败前最后的事件序列，帮助快速定位阶段。</div>
            </div>
            ${buildStatusBadge(currentTask)}
          </div>
          <div class="log-feed mt-5">
            ${buildLogFeed(currentTask?.events || [], "暂无可用日志。")}
          </div>
        </aside>
      </section>
    `;
  }

  return `
    <section class="grid gap-6 lg:grid-cols-[1.08fr_0.92fr]">
      <div class="glass-panel-strong rounded-[36px] p-6 md:p-8">
        <div class="flex flex-wrap items-center justify-between gap-4">
          ${heroHint}
          <span class="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/4 px-3 py-2 text-sm text-slate-300">
            <span class="status-dot ${hasToken ? "pending" : "error"}"></span>
            ${hasToken ? "可直接提交新任务" : "先到设置页配置连接"}
          </span>
        </div>
        <div class="mt-6">
          <div class="muted-label">Generate</div>
          <h1 class="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white md:text-5xl">上传一张图片，进入单任务状态机。</h1>
          <p class="mt-4 max-w-3xl text-base leading-7 text-slate-300 md:text-lg">
            生成页不再展示任务列表，只围绕当前任务的 idle、uploading、processing、completed、failed 五态切换。
          </p>
        </div>

        <form id="generate-form" class="mt-8 grid gap-5">
          <input id="generate-file-input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" class="hidden">
          <div id="generate-dropzone" class="dropzone rounded-[32px] p-6 md:p-8" tabindex="0" role="button" aria-controls="generate-file-input">
            <div class="grid gap-6 md:grid-cols-[1.08fr_0.92fr] md:items-center">
              <div>
                <div class="inline-flex items-center gap-2 rounded-full border border-orange-400/18 bg-orange-500/10 px-3 py-1.5 text-xs uppercase tracking-[0.2em] text-orange-100">
                  <i data-lucide="image-up" class="h-4 w-4"></i>
                  Drag or Click
                </div>
                <h2 class="mt-4 text-2xl font-semibold tracking-[-0.03em] text-white md:text-3xl">把输入图像直接扔进来。</h2>
                <p class="mt-3 max-w-xl text-sm leading-7 text-slate-300 md:text-base">
                  上传后会自动走 /v1/upload，再创建 /v1/tasks。当前页仅保留一个主任务视图，不再混入历史列表。
                </p>
                <div class="mt-6 flex flex-wrap gap-3">
                  <button data-action="open-file-dialog" type="button" class="pill-button inline-flex items-center gap-2 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-slate-950">
                    <i data-lucide="plus" class="h-4 w-4"></i>
                    选择图片
                  </button>
                  <button data-action="clear-selected-file" type="button" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-slate-200" ${upload.previewDataUrl ? "" : "disabled"}>
                    <i data-lucide="x" class="h-4 w-4"></i>
                    清除
                  </button>
                </div>
              </div>
              <div class="thumbnail-frame min-h-[240px]">
                ${upload.previewDataUrl
                  ? `<img src="${escapeHtml(upload.previewDataUrl)}" alt="待生成图片">`
                  : `<div class="thumbnail-placeholder"><div class="flex flex-col items-center gap-3 px-6 text-center"><i data-lucide="scan-search" class="h-11 w-11"></i><div><div class="text-base font-medium text-white">当前还没选图</div><div class="mt-1 text-sm text-slate-400">推荐 1:1 或主体明确的单张图片</div></div></div></div>`}
                <div class="thumbnail-overlay">${escapeHtml(upload.name || "等待输入图片")}</div>
              </div>
            </div>
          </div>

          <label class="grid gap-2 text-sm text-slate-300">
            <span class="muted-label">Callback URL (Optional)</span>
            <input id="generate-callback-url" type="url" value="${escapeHtml(upload.callbackUrl || "")}" placeholder="https://example.com/webhook" class="glass-panel rounded-[22px] border border-white/10 px-4 py-3 text-white outline-none placeholder:text-slate-500 focus:border-orange-400/40">
          </label>

          <div class="flex flex-wrap items-center justify-between gap-4 rounded-[28px] border border-white/10 bg-white/4 px-4 py-4 md:px-5">
            <div>
              <div class="text-sm font-medium text-white">${escapeHtml(upload.name || "尚未选择图片")}</div>
              <div class="form-status ${statusToneClass} mt-1">${escapeHtml(upload.statusMessage || (hasToken ? "图片就绪后会自动上传，然后直接开始生成。" : "请先到设置页保存 API Key 与 Base URL。"))}</div>
            </div>
            <div class="flex flex-wrap gap-3">
              <a href="#/settings" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-slate-200">
                <i data-lucide="sliders-horizontal" class="h-4 w-4"></i>
                连接设置
              </a>
              <button type="submit" class="pill-button inline-flex items-center gap-2 rounded-full bg-[linear-gradient(135deg,#f97316,#fb7185)] px-5 py-3 text-sm font-semibold text-white shadow-[0_16px_40px_rgba(249,115,22,0.18)]" ${upload.isSubmitting ? "disabled" : ""}>
                ${upload.isSubmitting ? '<span class="inline-spinner"></span>' : '<i data-lucide="sparkles" class="h-4 w-4"></i>'}
                ${upload.isSubmitting ? "正在创建任务…" : "开始生成"}
              </button>
            </div>
          </div>
        </form>
      </div>

      <aside class="self-start">
        <div class="glass-panel rounded-[30px] p-5 md:p-6">
          <div class="muted-label">Rules</div>
          <ul class="mt-4 grid gap-3 text-sm leading-7 text-slate-300">
            <li>• 生成页不展示任何历史任务卡片。</li>
            <li>• 新任务完成后自动切入 Three.js 完成态。</li>
            <li>• 不可取消阶段统一显示 disabled 按钮，避免 409。</li>
            <li>• 历史任务统一进入图库 Drawer 详情。</li>
          </ul>
        </div>
      </aside>
    </section>
  `;
}
