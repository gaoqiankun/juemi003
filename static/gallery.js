export function renderGalleryPage(ctx) {
  const {
    tasks,
    filter,
    taskPage,
    hasToken,
    selectedTaskId,
    helpers,
  } = ctx;
  const {
    escapeHtml,
    formatTime,
    formatRelativeTime,
    buildStatusBadge,
    buildTaskThumbnail,
    getTaskShortId,
    getFilterCount,
  } = helpers;

  return `
    <section class="grid gap-6">
      <div class="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div class="muted-label">Gallery</div>
          <h1 class="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white md:text-5xl">所有历史任务都留在这里。</h1>
          <p class="mt-4 max-w-3xl text-base leading-7 text-slate-300 md:text-lg">
            卡片网格只负责浏览与筛选，详情通过 Drawer 打开。删除成功后会立刻从当前列表移除。
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          ${[
            ["all", "全部"],
            ["processing", "处理中"],
            ["completed", "完成"],
            ["failed", "失败"],
          ].map(([value, label]) => `
            <button data-action="set-gallery-filter" data-filter="${value}" type="button" class="filter-pill ${filter === value ? "is-active" : ""}">
              ${label}
              <span class="ml-2 text-xs text-slate-400">${getFilterCount(value)}</span>
            </button>
          `).join("")}
        </div>
      </div>

      ${hasToken ? `
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          ${tasks.length ? tasks.map((task) => `
            <button type="button" data-action="open-drawer" data-task-id="${escapeHtml(task.taskId)}" class="task-card glass-panel rounded-[28px] border p-4 text-left ${selectedTaskId === task.taskId ? "is-selected" : ""}">
              <div class="grid gap-4">
                <div class="thumbnail-frame">
                  ${buildTaskThumbnail(task)}
                </div>
                <div class="flex items-start justify-between gap-4">
                  <div class="min-w-0">
                    <div class="text-xs uppercase tracking-[0.18em] text-slate-400">Task ${escapeHtml(getTaskShortId(task.taskId))}</div>
                    <h2 class="mt-2 truncate text-lg font-semibold tracking-[-0.03em] text-white">${escapeHtml(getTaskShortId(task.taskId))}</h2>
                    <div class="mt-1 text-sm text-slate-400">${escapeHtml(formatTime(task.createdAt))}</div>
                  </div>
                  ${buildStatusBadge(task)}
                </div>
                <div class="flex items-center justify-between text-sm text-slate-400">
                  <span>${escapeHtml(formatRelativeTime(task.updatedAt || task.createdAt))}</span>
                  <span class="inline-flex items-center gap-2 text-white">
                    <i data-lucide="panel-right-open" class="h-4 w-4"></i>
                    查看详情
                  </span>
                </div>
              </div>
            </button>
          `).join("") : `
            <div class="empty-state col-span-full grid gap-3 px-6 py-14 text-center">
              <div class="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl border border-white/10 bg-white/4 text-slate-100">
                <i data-lucide="gallery-horizontal-end" class="h-8 w-8"></i>
              </div>
              <div>
                <h2 class="text-xl font-semibold text-white">当前筛选下没有任务</h2>
                <p class="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-400">切换筛选条件，或返回生成页提交一个新任务。</p>
              </div>
              <div>
                <a href="#/" class="pill-button inline-flex items-center gap-2 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-slate-950">
                  <i data-lucide="sparkles" class="h-4 w-4"></i>
                  去生成页
                </a>
              </div>
            </div>
          `}
        </div>
        <div class="flex justify-center pt-2">
          <button data-action="load-more-tasks" type="button" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-slate-200" ${taskPage.hasMore ? "" : "hidden"} ${taskPage.isLoading ? "disabled" : ""}>
            <i data-lucide="chevrons-down" class="h-4 w-4"></i>
            ${taskPage.isLoading ? "加载中…" : "加载更多"}
          </button>
        </div>
      ` : `
        <div class="empty-state grid gap-4 px-6 py-14 text-center">
          <div class="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl border border-white/10 bg-white/4 text-slate-100">
            <i data-lucide="plug-zap" class="h-8 w-8"></i>
          </div>
          <div>
            <h2 class="text-xl font-semibold text-white">先配置连接，再浏览图库</h2>
            <p class="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-400">保存 API Base URL 和 API Key 后，图库会自动拉取分页任务列表。</p>
          </div>
          <div>
            <a href="#/settings" class="pill-button inline-flex items-center gap-2 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-slate-950">
              <i data-lucide="sliders-horizontal" class="h-4 w-4"></i>
              打开设置
            </a>
          </div>
        </div>
      `}
    </section>
  `;
}

export function renderGalleryDrawer(ctx) {
  const {
    task,
    canCancel,
    helpers,
  } = ctx;
  const {
    escapeHtml,
    formatTime,
    formatTaskStatus,
    formatStage,
    buildStatusBadge,
    buildLogFeed,
    getTaskShortId,
  } = helpers;

  if (!task) {
    return `
      <div class="flex items-start justify-between gap-4">
        <div>
          <div class="muted-label">Detail Drawer</div>
          <h2 id="drawer-title" class="mt-2 text-2xl font-semibold tracking-[-0.03em] text-white">选择一个任务</h2>
          <p class="mt-2 text-sm leading-6 text-slate-400">点击卡片后，Drawer 会展示 Three.js 查看器、下载、删除与实时日志。</p>
        </div>
        <button data-action="close-drawer" type="button" class="pill-button ghost-button rounded-full p-2 text-slate-200">
          <i data-lucide="x" class="h-5 w-5"></i>
        </button>
      </div>
    `;
  }

  const downloadUrl = task.resolvedArtifactUrl || task.rawArtifactUrl || "";
  return `
    <div class="flex items-start justify-between gap-4">
      <div>
        <div class="muted-label">Detail Drawer</div>
        <h2 id="drawer-title" class="mt-2 text-2xl font-semibold tracking-[-0.03em] text-white">任务 ${escapeHtml(getTaskShortId(task.taskId))}</h2>
        <div class="mt-3 flex flex-wrap items-center gap-3">
          ${buildStatusBadge(task)}
          <span class="text-sm text-slate-400">${escapeHtml(formatStage(task.currentStage || task.status))}</span>
        </div>
      </div>
      <button data-action="close-drawer" type="button" class="pill-button ghost-button rounded-full p-2 text-slate-200">
        <i data-lucide="x" class="h-5 w-5"></i>
      </button>
    </div>

    <div class="mt-6 viewer-stage h-[300px] md:h-[360px]">
      <div id="drawer-viewer" class="h-full w-full"></div>
    </div>

    <div class="mt-6 grid gap-4 md:grid-cols-2">
      <div class="meta-card">
        <span class="muted-label">Task ID</span>
        <strong>${escapeHtml(task.taskId)}</strong>
      </div>
      <div class="meta-card">
        <span class="muted-label">Created</span>
        <strong>${escapeHtml(formatTime(task.createdAt))}</strong>
      </div>
      <div class="meta-card">
        <span class="muted-label">Updated</span>
        <strong>${escapeHtml(formatTime(task.updatedAt || task.lastSeenAt))}</strong>
      </div>
      <div class="meta-card">
        <span class="muted-label">Status</span>
        <strong>${escapeHtml(formatTaskStatus(task.status))}</strong>
      </div>
    </div>

    ${task.note ? `
      <div class="mt-4 rounded-[24px] border border-white/10 bg-white/4 px-4 py-4 text-sm leading-7 text-slate-300">${escapeHtml(task.note)}</div>
    ` : ""}
    ${task.error?.message ? `
      <div class="mt-4 rounded-[24px] border border-rose-400/18 bg-rose-500/10 px-4 py-4 text-sm leading-7 text-rose-100">
        ${escapeHtml(task.error.failed_stage ? `${task.error.message} (${task.error.failed_stage})` : task.error.message)}
      </div>
    ` : ""}

    <div class="mt-5 flex flex-wrap gap-3">
      <button data-action="refresh-drawer-task" type="button" class="card-action inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium">
        <i data-lucide="refresh-cw" class="h-4 w-4"></i>
        刷新
      </button>
      ${["succeeded", "failed", "cancelled"].includes(task.status) ? "" : `
        <button data-action="cancel-drawer-task" type="button" class="card-action inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium" ${canCancel ? "" : "disabled"}>
          <i data-lucide="ban" class="h-4 w-4"></i>
          ${task.pendingCancel ? "取消中…" : "取消任务"}
        </button>
      `}
      <a href="${escapeHtml(downloadUrl || "#")}" ${downloadUrl ? 'download="model.glb" target="_blank" rel="noopener noreferrer"' : ''} class="card-action inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium ${downloadUrl ? "" : "pointer-events-none opacity-50"}">
        <i data-lucide="download" class="h-4 w-4"></i>
        下载模型
      </a>
      <button data-action="delete-drawer-task" type="button" class="card-action danger inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium" ${task.pendingDelete ? "disabled" : ""}>
        <i data-lucide="trash-2" class="h-4 w-4"></i>
        ${task.pendingDelete ? "删除中…" : "删除任务"}
      </button>
    </div>

    <div class="mt-6 rounded-[28px] border border-white/10 bg-white/4 p-4">
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="muted-label">Logs</div>
          <div class="mt-1 text-sm text-slate-400">任务事件会在这里回放或实时更新。</div>
        </div>
        <span class="text-sm text-slate-400">${task.events.length} 条</span>
      </div>
      <div class="log-feed mt-4">
        ${buildLogFeed(task.events, "暂无任务事件。")}
      </div>
    </div>
  `;
}
