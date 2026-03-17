export function renderSettingsPage(ctx) {
  const {
    config,
    ready,
    revealApiKey,
    helpers,
  } = ctx;
  const { escapeHtml } = helpers;
  const readyTone = ready.tone === "ready" ? "ready" : "error";

  return `
    <section class="grid gap-6 lg:grid-cols-[1.02fr_0.98fr]">
      <div class="glass-panel-strong rounded-[36px] p-6 md:p-8">
        <div class="muted-label">Settings</div>
        <h1 class="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white md:text-5xl">把连接配置固定下来。</h1>
        <p class="mt-4 max-w-3xl text-base leading-7 text-slate-300 md:text-lg">
          设置页负责存储 API Key / Base URL，并用 /ready 做连通性测试。保存后立即 toast 反馈。
        </p>

        <form id="settings-form" class="mt-8 grid gap-5">
          <label class="grid gap-2 text-sm text-slate-300">
            <span class="muted-label">API Key</span>
            <div class="relative">
              <input id="settings-api-key" name="token" type="${revealApiKey ? "text" : "password"}" value="${escapeHtml(config.token || "")}" autocomplete="off" spellcheck="false" placeholder="sk-..." class="glass-panel w-full rounded-[22px] border border-white/10 px-4 py-3 pr-28 text-white outline-none placeholder:text-slate-500 focus:border-orange-400/40">
              <button data-action="toggle-api-key-visibility" type="button" class="pill-button ghost-button absolute right-2 top-1/2 inline-flex -translate-y-1/2 items-center gap-2 rounded-full px-3 py-2 text-xs font-medium text-slate-200">
                <i data-lucide="${revealApiKey ? "eye-off" : "eye"}" class="h-4 w-4"></i>
                ${revealApiKey ? "隐藏" : "显示"}
              </button>
            </div>
          </label>

          <label class="grid gap-2 text-sm text-slate-300">
            <span class="muted-label">API Base URL</span>
            <input id="settings-base-url" name="baseUrl" type="url" value="${escapeHtml(config.baseUrl || "")}" placeholder="http://localhost:18001" class="glass-panel rounded-[22px] border border-white/10 px-4 py-3 text-white outline-none placeholder:text-slate-500 focus:border-orange-400/40">
          </label>

          <div class="flex flex-wrap gap-3 pt-2">
            <button type="submit" class="pill-button inline-flex items-center gap-2 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-slate-950">
              <i data-lucide="save" class="h-4 w-4"></i>
              保存配置
            </button>
            <button data-action="test-ready" type="button" class="pill-button ghost-button inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-slate-200">
              <i data-lucide="activity" class="h-4 w-4"></i>
              测试 /ready
            </button>
          </div>
        </form>
      </div>

      <aside class="grid gap-5 self-start">
        <div class="glass-panel rounded-[30px] p-5 md:p-6">
          <div class="flex items-center justify-between gap-4">
            <div>
              <div class="muted-label">Connection Status</div>
              <div class="mt-2 text-xl font-semibold tracking-[-0.03em] text-white">${escapeHtml(ready.label || "等待检测")}</div>
              <div class="mt-2 text-sm leading-7 text-slate-400">${escapeHtml(ready.detail || "保存配置后，可随时用 /ready 验证服务状态。")}</div>
            </div>
            <span class="status-dot ${readyTone}"></span>
          </div>
        </div>

        <div class="glass-panel rounded-[30px] p-5 md:p-6">
          <div class="muted-label">Persistence</div>
          <ul class="mt-4 grid gap-3 text-sm leading-7 text-slate-300">
            <li>• API Key 与 Base URL 保存到 localStorage。</li>
            <li>• 生成页当前任务只在当前浏览会话中保留。</li>
            <li>• 修改配置后会自动刷新任务列表与连接状态。</li>
          </ul>
        </div>
      </aside>
    </section>
  `;
}
