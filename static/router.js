import { createIcons, icons } from "lucide";
import { renderGeneratePage } from "./generate.js";
import { renderGalleryPage, renderGalleryDrawer } from "./gallery.js";
import { renderSettingsPage } from "./settings.js";
import { Viewer3D, renderModelThumbnail } from "./viewer3d.js";

const STORAGE_KEYS = {
  config: "gen3d.web.config.v3",
  currentTask: "gen3d.web.current-task.v1",
};

const TASK_PAGE_LIMIT = 20;
const POLL_INTERVAL_MS = 3000;
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);
const CANCELLABLE_STATUSES = new Set(["gpu_queued"]);
const ACTIVE_STATUSES = new Set([
  "submitted",
  "queued",
  "preprocessing",
  "gpu_queued",
  "gpu_ss",
  "gpu_shape",
  "gpu_material",
  "exporting",
  "uploading",
]);

const STATUS_LABELS = {
  submitted: "Submitted",
  queued: "Queued",
  preprocessing: "Preprocessing",
  gpu_queued: "GPU Queued",
  gpu_ss: "Sparse Structure",
  gpu_shape: "Geometry",
  gpu_material: "Material",
  exporting: "Exporting",
  uploading: "Uploading",
  succeeded: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const STAGE_LABELS = {
  submitted: "任务已提交，等待排队",
  queued: "在队列中等待 GPU 资源",
  preprocessing: "预处理中：读取并规范化图片",
  gpu_queued: "预处理完成，等待 GPU stage",
  gpu_ss: "Sparse Structure 阶段",
  gpu_shape: "Shape / Geometry 阶段",
  gpu_material: "Material / PBR 阶段",
  exporting: "导出 GLB 产物",
  uploading: "上传 artifact",
  succeeded: "任务已完成",
  failed: "任务执行失败",
  cancelled: "任务已取消",
};

const DEFAULT_PROGRESS_BY_STATUS = {
  submitted: 4,
  queued: 8,
  preprocessing: 18,
  gpu_queued: 28,
  gpu_ss: 42,
  gpu_shape: 62,
  gpu_material: 82,
  exporting: 92,
  uploading: 96,
  succeeded: 100,
  failed: 100,
  cancelled: 0,
};

const ROUTES = new Set(["/", "/gallery", "/settings"]);

const state = {
  route: "/",
  config: {
    baseUrl: getDefaultBaseUrl(),
    token: "",
  },
  authState: "missing",
  ready: {
    tone: "error",
    label: "连接未检测",
    detail: "保存配置后使用 /ready 检测服务状态。",
  },
  settingsUi: {
    revealApiKey: false,
  },
  tasks: new Map(),
  subscriptions: new Map(),
  taskPage: {
    limit: TASK_PAGE_LIMIT,
    nextCursor: "",
    hasMore: false,
    isLoading: false,
  },
  galleryFilter: "all",
  generate: {
    file: null,
    previewDataUrl: "",
    uploadedUrl: "",
    uploadId: "",
    name: "",
    callbackUrl: "",
    isUploading: false,
    uploadProgress: 0,
    isSubmitting: false,
    statusMessage: "",
    statusTone: "info",
    currentTaskId: loadCurrentTaskId(),
    viewerKey: "",
  },
  drawer: {
    open: false,
    taskId: "",
    trigger: null,
    lastViewerKey: "",
  },
  confirm: null,
  renderQueued: false,
  thumbnailCache: new Map(),
  thumbnailJobs: new Map(),
  viewers: {
    generate: null,
    drawer: null,
  },
  pendingFocus: null,
};

const elements = {
  appShell: document.getElementById("app-shell"),
  routeContent: document.getElementById("route-content"),
  connectionDot: document.getElementById("connection-dot"),
  connectionLabel: document.getElementById("connection-label"),
  connectionCaption: document.getElementById("connection-caption"),
  mobileNavButton: document.getElementById("mobile-nav-button"),
  mobileNavPanel: document.getElementById("mobile-nav-panel"),
  drawerBackdrop: document.getElementById("drawer-backdrop"),
  drawerSurface: document.getElementById("drawer-surface"),
  drawerScroll: document.getElementById("drawer-scroll"),
  confirmModal: document.getElementById("confirm-modal"),
  confirmTitle: document.getElementById("confirm-title"),
  confirmCopy: document.getElementById("confirm-copy"),
  confirmCancelButton: document.getElementById("confirm-cancel-button"),
  confirmAcceptButton: document.getElementById("confirm-accept-button"),
  toastStack: document.getElementById("toast-stack"),
};

function getDefaultBaseUrl() {
  const origin = window.location.origin;
  if (!origin || origin === "null") {
    return "http://localhost:18001";
  }
  return origin;
}

function loadCurrentTaskId() {
  try {
    return String(sessionStorage.getItem(STORAGE_KEYS.currentTask) || "").trim();
  } catch {
    return "";
  }
}

function persistCurrentTaskId(taskId) {
  try {
    if (taskId) {
      sessionStorage.setItem(STORAGE_KEYS.currentTask, taskId);
    } else {
      sessionStorage.removeItem(STORAGE_KEYS.currentTask);
    }
  } catch {
    // ignore sessionStorage failures in private contexts
  }
}

function normalizeBaseUrl(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return getDefaultBaseUrl();
  }
  return trimmed.replace(/\/+$/, "");
}

function ensureTrailingSlash(url) {
  return url.endsWith("/") ? url : `${url}/`;
}

function buildApiUrl(path) {
  return new URL(String(path).replace(/^\/+/, ""), ensureTrailingSlash(state.config.baseUrl)).toString();
}

function authHeaders(json = false) {
  const headers = {};
  if (state.config.token) {
    headers.Authorization = `Bearer ${state.config.token}`;
  }
  if (json) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

function defaultProgressForStatus(status) {
  return DEFAULT_PROGRESS_BY_STATUS[status] ?? 0;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatRelativeTime(value) {
  if (!value) {
    return "刚刚";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  const diffMs = date.getTime() - Date.now();
  const diffMinutes = Math.round(diffMs / 60000);
  const formatter = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
  if (Math.abs(diffMinutes) < 60) {
    return formatter.format(diffMinutes, "minute");
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return formatter.format(diffHours, "hour");
  }
  const diffDays = Math.round(diffHours / 24);
  return formatter.format(diffDays, "day");
}

function formatTaskStatus(status) {
  return STATUS_LABELS[status] || String(status || "unknown").replace(/_/g, " ");
}

function formatStage(status) {
  return STAGE_LABELS[status] || formatTaskStatus(status);
}

function getVisualStatus(status) {
  if (status === "succeeded") {
    return "done";
  }
  if (status === "failed" || status === "cancelled") {
    return "failed";
  }
  if (status === "submitted" || status === "queued") {
    return "queued";
  }
  return "processing";
}

function getStatusIcon(status) {
  const visual = getVisualStatus(status);
  if (visual === "done") {
    return "badge-check";
  }
  if (visual === "failed") {
    return "octagon-x";
  }
  if (visual === "queued") {
    return "clock-3";
  }
  return "loader-circle";
}

function isActiveStatus(status) {
  return ACTIVE_STATUSES.has(status);
}

function isPreviewableUrl(url) {
  return /^https?:\/\//i.test(String(url || ""));
}

function isCancellable(task) {
  return Boolean(task) && CANCELLABLE_STATUSES.has(String(task.status || "")) && !task.pendingCancel;
}

function getTaskShortId(taskId) {
  return String(taskId || "").slice(-8) || "--------";
}

function compareTaskRecords(a, b) {
  const timeA = new Date(a.createdAt || a.submittedAt || 0).getTime();
  const timeB = new Date(b.createdAt || b.submittedAt || 0).getTime();
  return timeB - timeA;
}

function buildStatusBadge(task) {
  if (!task) {
    return "";
  }
  const visual = getVisualStatus(task.status);
  return `
    <span class="status-badge ${visual}">
      <i data-lucide="${getStatusIcon(task.status)}" class="h-4 w-4"></i>
      ${escapeHtml(formatTaskStatus(task.status))}
    </span>
  `;
}

function buildTaskThumbnail(task) {
  if (task.thumbnailUrl) {
    return `
      <img src="${escapeHtml(task.thumbnailUrl)}" alt="${escapeHtml(task.taskId)} 3D thumbnail">
      <div class="thumbnail-overlay">3D 缩略图 · ${escapeHtml(task.model)}</div>
    `;
  }
  if (task.previewDataUrl) {
    return `
      <img src="${escapeHtml(task.previewDataUrl)}" alt="${escapeHtml(task.taskId)} input preview">
      <div class="thumbnail-overlay">输入图片预览</div>
    `;
  }
  const subtitle = task.status === "succeeded"
    ? task.thumbnailState === "loading"
      ? "正在生成 3D 缩略图…"
      : "暂无缩略图，可在详情中查看模型"
    : "等待模型产物生成";
  return `
    <div class="thumbnail-placeholder">
      <div class="flex flex-col items-center gap-3 px-6 text-center">
        <i data-lucide="box" class="h-10 w-10"></i>
        <div>
          <div class="text-sm font-medium text-white">${escapeHtml(formatTaskStatus(task.status))}</div>
          <div class="mt-1 text-xs text-slate-400">${escapeHtml(subtitle)}</div>
        </div>
      </div>
    </div>
    <div class="thumbnail-overlay">${escapeHtml(getTaskShortId(task.taskId))} · ${escapeHtml(task.model)}</div>
  `;
}

function buildLogFeed(events, emptyMessage) {
  if (!Array.isArray(events) || !events.length) {
    return `
      <div class="empty-state px-4 py-8 text-center text-sm text-slate-400">
        ${escapeHtml(emptyMessage)}
      </div>
    `;
  }
  return events
    .slice()
    .reverse()
    .map((eventItem) => `
      <div class="log-item">
        <div class="flex items-center justify-between gap-3">
          <strong class="inline-flex items-center gap-2 text-sm text-white">
            <i data-lucide="sparkles" class="h-4 w-4"></i>
            ${escapeHtml(eventItem.event || eventItem.status || "event")}
          </strong>
          <time class="text-xs text-slate-400">${escapeHtml(formatTime(eventItem.timestamp))}</time>
        </div>
        <div class="mt-2 text-sm text-slate-300">
          状态：${escapeHtml(formatTaskStatus(eventItem.status))} · 阶段：${escapeHtml(formatStage(eventItem.currentStage || eventItem.status))}
        </div>
        <div class="mt-1 text-xs text-slate-400">
          进度 ${Math.max(0, Math.min(100, Number(eventItem.progress) || 0))}% · 来源 ${escapeHtml(eventItem.source || "unknown")}
          ${eventItem.message ? ` · ${escapeHtml(eventItem.message)}` : ""}
        </div>
      </div>
    `)
    .join("");
}

function getFilterCount(filter) {
  return getFilteredTasks(filter).length;
}

function getFilteredTasks(filter = state.galleryFilter) {
  const tasks = Array.from(state.tasks.values()).sort(compareTaskRecords);
  if (filter === "processing") {
    return tasks.filter((task) => isActiveStatus(task.status));
  }
  if (filter === "completed") {
    return tasks.filter((task) => task.status === "succeeded");
  }
  if (filter === "failed") {
    return tasks.filter((task) => task.status === "failed" || task.status === "cancelled");
  }
  return tasks;
}

function normalizeTaskRecord(task) {
  const taskId = task.taskId || task.task_id;
  const status = String(task.status || task.statusLabel || task.status_label || "submitted");
  const createdAt = task.createdAt || task.created_at || task.submittedAt || task.submitted_at || new Date().toISOString();
  const updatedAt = task.updatedAt || task.updated_at || task.finishedAt || task.finished_at || createdAt;
  const rawArtifactUrl = task.rawArtifactUrl || task.raw_artifact_url || "";
  const artifacts = Array.isArray(task.artifacts) ? task.artifacts : [];
  return {
    taskId,
    model: task.model || "trellis",
    inputUrl: task.inputUrl || task.input_url || "",
    createdAt,
    submittedAt: task.submittedAt || task.submitted_at || createdAt,
    updatedAt,
    lastSeenAt: task.lastSeenAt || task.last_seen_at || updatedAt,
    status,
    statusLabel: task.statusLabel || task.status_label || formatTaskStatus(status),
    progress: Number.isFinite(task.progress) ? Number(task.progress) : defaultProgressForStatus(status),
    currentStage: task.currentStage || task.current_stage || status,
    queuePosition: task.queuePosition ?? task.queue_position ?? null,
    estimatedWaitSeconds: task.estimatedWaitSeconds ?? task.estimated_wait_seconds ?? null,
    estimatedFinishAt: task.estimatedFinishAt || task.estimated_finish_at || null,
    artifacts,
    error: task.error || null,
    events: Array.isArray(task.events) ? task.events.slice(-30) : [],
    transport: task.transport || "idle",
    note: task.note || "",
    resolvedArtifactUrl: task.resolvedArtifactUrl || task.resolved_artifact_url || "",
    rawArtifactUrl,
    previewDataUrl: task.previewDataUrl || task.preview_data_url || "",
    thumbnailUrl: task.thumbnailUrl || task.thumbnail_url || "",
    thumbnailState: task.thumbnailState || task.thumbnail_state || "idle",
    pendingDelete: Boolean(task.pendingDelete),
    pendingCancel: Boolean(task.pendingCancel),
    successRefreshScheduled: Boolean(task.successRefreshScheduled),
  };
}

function loadConfig() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEYS.config) || "{}");
    state.config.baseUrl = normalizeBaseUrl(saved.baseUrl || getDefaultBaseUrl());
    state.config.token = String(saved.token || "").trim();
  } catch (error) {
    console.warn("failed to parse saved config", error);
    state.config.baseUrl = getDefaultBaseUrl();
    state.config.token = "";
  }
  state.authState = state.config.token ? "configured" : "missing";
}

function persistConfig(nextConfig) {
  state.config.baseUrl = normalizeBaseUrl(nextConfig?.baseUrl || state.config.baseUrl || getDefaultBaseUrl());
  state.config.token = String(nextConfig?.token ?? state.config.token ?? "").trim();
  state.authState = state.config.token ? "configured" : "missing";
  localStorage.setItem(STORAGE_KEYS.config, JSON.stringify(state.config));
  updateConnectionUi();
}

function updateConnectionUi() {
  const tone = state.ready.tone === "ready" ? "ready" : state.config.token ? "error" : "empty";
  elements.connectionDot.className = `status-dot ${tone}`;
  elements.connectionLabel.textContent = state.ready.tone === "ready"
    ? "服务连接正常"
    : state.config.token
      ? "等待服务响应"
      : "未配置 API Key";
  elements.connectionCaption.textContent = state.ready.tone === "ready"
    ? state.ready.detail
    : state.config.token
      ? state.config.baseUrl
      : "打开设置页以保存连接信息";
}

function setReadyState(tone, label, detail = label) {
  state.ready = { tone, label, detail };
  updateConnectionUi();
  queueRender();
}

function setGenerateStatus(message, tone = "info") {
  state.generate.statusMessage = message;
  state.generate.statusTone = tone;
  queueRender();
}

function queueRender() {
  if (state.renderQueued) {
    return;
  }
  state.renderQueued = true;
  window.requestAnimationFrame(async () => {
    state.renderQueued = false;
    await renderApp();
  });
}

function scheduleFocus(callback) {
  state.pendingFocus = callback;
  queueRender();
}

function flushPendingFocus() {
  if (!state.pendingFocus) {
    return;
  }
  const callback = state.pendingFocus;
  state.pendingFocus = null;
  window.requestAnimationFrame(() => {
    try {
      callback();
    } catch (error) {
      console.warn("focus restore failed", error);
    }
  });
}

function refreshIcons() {
  try {
    createIcons({
      icons,
      attrs: {
        "stroke-width": 1.8,
      },
    });
  } catch (error) {
    console.warn("lucide icon refresh failed", error);
  }
}

function ensureTask(taskId, patch = {}) {
  const current = state.tasks.get(taskId);
  const merged = normalizeTaskRecord({
    ...(current || { taskId }),
    ...patch,
    taskId,
  });
  state.tasks.set(taskId, merged);
  return merged;
}

function removeTask(taskId) {
  stopSubscription(taskId);
  state.tasks.delete(taskId);
  if (state.generate.currentTaskId === taskId) {
    setCurrentTaskId("");
    state.generate.statusMessage = "";
    state.generate.statusTone = "info";
  }
  if (state.drawer.taskId === taskId) {
    closeDrawer({ restoreFocus: false });
  }
  queueRender();
}

function resetTaskState() {
  Array.from(state.subscriptions.keys()).forEach((taskId) => stopSubscription(taskId));
  state.tasks.clear();
  state.taskPage.nextCursor = "";
  state.taskPage.hasMore = false;
  state.taskPage.isLoading = false;
  if (!state.generate.currentTaskId) {
    persistCurrentTaskId("");
  }
}

function setCurrentTaskId(taskId) {
  state.generate.currentTaskId = taskId || "";
  persistCurrentTaskId(state.generate.currentTaskId);
}

function buildTaskListUrl(before = "") {
  const url = new URL(buildApiUrl("/v1/tasks"));
  url.searchParams.set("limit", String(state.taskPage.limit));
  if (before) {
    url.searchParams.set("before", before);
  }
  return url.toString();
}

function applyTaskPage(payload) {
  state.taskPage.nextCursor = payload.nextCursor || payload.next_cursor || "";
  state.taskPage.hasMore = Boolean(payload.hasMore ?? payload.has_more);
  state.taskPage.isLoading = false;
}

function syncCurrentTaskSelection() {
  if (state.generate.currentTaskId && state.tasks.has(state.generate.currentTaskId)) {
    return;
  }
  const latestActive = Array.from(state.tasks.values())
    .filter((task) => isActiveStatus(task.status))
    .sort(compareTaskRecords)[0];
  if (latestActive) {
    setCurrentTaskId(latestActive.taskId);
    return;
  }
  if (state.generate.currentTaskId && !state.tasks.has(state.generate.currentTaskId)) {
    setCurrentTaskId("");
  }
}

async function replaceTasksFromServer(taskSummaries, { append = false } = {}) {
  const nextTasks = append ? new Map(state.tasks) : new Map();
  for (const summary of taskSummaries) {
    const taskId = summary.taskId || summary.task_id;
    if (!taskId) {
      continue;
    }
    const current = state.tasks.get(taskId);
    nextTasks.set(
      taskId,
      normalizeTaskRecord({
        ...(current || {}),
        taskId,
        model: summary.model || current?.model || "trellis",
        inputUrl: summary.inputUrl || summary.input_url || current?.inputUrl || "",
        createdAt: summary.createdAt || summary.created_at || current?.createdAt,
        updatedAt: summary.finishedAt || summary.finished_at || current?.updatedAt || current?.lastSeenAt,
        lastSeenAt: new Date().toISOString(),
        status: String(summary.status || current?.status || "submitted"),
        statusLabel: formatTaskStatus(String(summary.status || current?.status || "submitted")),
        currentStage: current?.currentStage || String(summary.status || current?.status || "submitted"),
        progress: current?.progress ?? defaultProgressForStatus(String(summary.status || "submitted")),
        artifacts: summary.artifactUrl || summary.artifact_url
          ? [{ type: "glb", url: summary.artifactUrl || summary.artifact_url }]
          : current?.artifacts || [],
        rawArtifactUrl: summary.artifactUrl || summary.artifact_url || current?.rawArtifactUrl || "",
        transport: TERMINAL_STATUSES.has(String(summary.status || "")) ? "complete" : current?.transport || "idle",
        resolvedArtifactUrl: current?.resolvedArtifactUrl || "",
        previewDataUrl: current?.previewDataUrl || "",
        note: current?.note || "",
      }),
    );
  }

  if (!append) {
    Array.from(state.subscriptions.keys()).forEach((taskId) => {
      if (!nextTasks.has(taskId)) {
        stopSubscription(taskId);
      }
    });
  }

  state.tasks = nextTasks;
  for (const task of state.tasks.values()) {
    await hydrateArtifact(task);
  }
  syncCurrentTaskSelection();
}

async function refreshTaskList({ append = false, resubscribe = false, silent = false } = {}) {
  persistConfig();
  if (!state.config.baseUrl) {
    throw new Error("请先填写 API Base URL");
  }
  if (!state.config.token) {
    state.authState = "missing";
    resetTaskState();
    queueRender();
    return;
  }

  state.taskPage.isLoading = true;
  queueRender();

  const url = append ? buildTaskListUrl(state.taskPage.nextCursor) : buildTaskListUrl();
  const response = await fetch(url, {
    headers: authHeaders(false),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  state.authState = "configured";
  const payload = await response.json();
  await replaceTasksFromServer(Array.isArray(payload.items) ? payload.items : [], { append });
  applyTaskPage(payload);
  if (resubscribe) {
    await restoreSubscriptions();
  }
  if (!silent && state.route === "/gallery") {
    showToast({ title: append ? "更多任务已加载" : "图库已刷新", message: `当前共有 ${state.tasks.size} 条任务记录。`, tone: "success" });
  }
  queueRender();
}

async function refreshTask(taskId, { silent = true } = {}) {
  const response = await fetch(buildApiUrl(`/v1/tasks/${encodeURIComponent(taskId)}`), {
    headers: authHeaders(false),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  const payload = await response.json();
  state.authState = "configured";
  await applyTaskSnapshot(taskId, payload, "snapshot");
  if (!silent) {
    showToast({ title: "任务已刷新", message: `任务 ${getTaskShortId(taskId)} 的详情已更新。`, tone: "success" });
  }
}

function appendTaskEvent(taskId, payload, source) {
  const task = state.tasks.get(taskId);
  if (!task) {
    return;
  }
  const eventEntry = {
    event: payload.event || payload.status || source,
    status: payload.status || task.status,
    progress: Number.isFinite(payload.progress) ? Number(payload.progress) : task.progress,
    currentStage: payload.currentStage || payload.current_stage || task.currentStage,
    timestamp: new Date().toISOString(),
    source,
    message: payload.message || payload.metadata?.message || "",
  };
  const previous = task.events[task.events.length - 1];
  if (
    previous &&
    previous.event === eventEntry.event &&
    previous.status === eventEntry.status &&
    previous.progress === eventEntry.progress &&
    previous.currentStage === eventEntry.currentStage &&
    previous.message === eventEntry.message
  ) {
    return;
  }
  task.events.push(eventEntry);
  task.events = task.events.slice(-30);
}

async function applyTaskSnapshot(taskId, payload, source) {
  const previous = state.tasks.get(taskId);
  const status = String(payload.status || previous?.status || "submitted");
  const task = ensureTask(taskId, {
    model: payload.model || previous?.model || "trellis",
    inputUrl: payload.inputUrl || payload.input_url || previous?.inputUrl || "",
    status,
    statusLabel: formatTaskStatus(status),
    progress: Number.isFinite(payload.progress) ? Number(payload.progress) : defaultProgressForStatus(status),
    currentStage: payload.currentStage || payload.current_stage || status,
    queuePosition: payload.queuePosition ?? payload.queue_position ?? null,
    estimatedWaitSeconds: payload.estimatedWaitSeconds ?? payload.estimated_wait_seconds ?? null,
    estimatedFinishAt: payload.estimatedFinishAt || payload.estimated_finish_at || null,
    createdAt: payload.createdAt || payload.created_at || previous?.createdAt || new Date().toISOString(),
    updatedAt: payload.updatedAt || payload.updated_at || new Date().toISOString(),
    lastSeenAt: new Date().toISOString(),
    error: payload.error || null,
    artifacts: Array.isArray(payload.artifacts) ? payload.artifacts : previous?.artifacts || [],
    rawArtifactUrl: Array.isArray(payload.artifacts) && payload.artifacts.length > 0
      ? String(payload.artifacts.find((artifact) => artifact.type === "glb")?.url || payload.artifacts[0]?.url || "")
      : previous?.rawArtifactUrl || "",
    transport: source === "sse" ? "sse" : source === "polling" ? "polling" : previous?.transport || "idle",
  });

  appendTaskEvent(taskId, payload, source);
  await hydrateArtifact(task);
  const hydratedTask = state.tasks.get(taskId) || task;

  if (hydratedTask.status === "succeeded" && !hydratedTask.resolvedArtifactUrl && !hydratedTask.successRefreshScheduled) {
    ensureTask(taskId, { successRefreshScheduled: true, note: hydratedTask.note || "模型已完成，正在补拉 artifact 详情…" });
    refreshTask(taskId, { silent: true })
      .catch((error) => {
        console.warn("post-success refresh failed", error);
      })
      .finally(() => {
        const current = state.tasks.get(taskId);
        if (current) {
          ensureTask(taskId, { successRefreshScheduled: false });
          queueRender();
        }
      });
  }

  if (TERMINAL_STATUSES.has(hydratedTask.status)) {
    stopSubscription(taskId);
  }
  if (state.generate.currentTaskId === taskId || (isActiveStatus(hydratedTask.status) && !state.generate.currentTaskId)) {
    setCurrentTaskId(taskId);
  }
  queueRender();
}

async function applyEventPayload(taskId, payload, source) {
  const metadata = payload.metadata || {};
  await applyTaskSnapshot(
    taskId,
    {
      status: payload.status,
      progress: payload.progress,
      currentStage: payload.currentStage,
      updatedAt: new Date().toISOString(),
      error: metadata.error || metadata.failed_stage || metadata.message
        ? {
            message: metadata.message || metadata.error || "",
            failed_stage: metadata.failed_stage || metadata.stage || null,
          }
        : state.tasks.get(taskId)?.error || null,
      artifacts: metadata.artifacts || state.tasks.get(taskId)?.artifacts || [],
    },
    source,
  );
}

function resolveArtifactUrl(url) {
  const raw = String(url || "").trim();
  if (!raw) {
    return "";
  }
  if (raw.startsWith("/")) {
    return buildApiUrl(raw);
  }
  return raw;
}

function buildLocalArtifactCandidates(taskId, fileUrl) {
  let fileName = "model.glb";
  try {
    const path = decodeURIComponent(new URL(fileUrl).pathname);
    const parts = path.split("/").filter(Boolean);
    fileName = parts[parts.length - 1] || fileName;
  } catch (error) {
    console.warn("failed to parse local artifact URL", error);
  }
  const root = ensureTrailingSlash(state.config.baseUrl);
  return Array.from(new Set([
    new URL(`artifacts/${encodeURIComponent(taskId)}/${encodeURIComponent(fileName)}`, root).toString(),
    new URL(`v1/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(fileName)}`, root).toString(),
    new URL(`${encodeURIComponent(taskId)}/${encodeURIComponent(fileName)}`, new URL("artifacts/", root)).toString(),
  ]));
}

async function probeUrl(url) {
  try {
    const response = await fetch(url, { method: "HEAD", cache: "no-store" });
    if (response.ok) {
      return true;
    }
    if (response.status === 405) {
      const fallback = await fetch(url, { cache: "no-store" });
      return fallback.ok;
    }
    return false;
  } catch {
    return false;
  }
}

async function hydrateArtifact(task) {
  if (task.status !== "succeeded" || !Array.isArray(task.artifacts) || task.artifacts.length === 0) {
    ensureTask(task.taskId, {
      resolvedArtifactUrl: "",
      rawArtifactUrl: task.rawArtifactUrl || "",
    });
    return;
  }

  const glb = task.artifacts.find((artifact) => artifact.type === "glb") || task.artifacts[0];
  if (!glb || !glb.url) {
    ensureTask(task.taskId, {
      resolvedArtifactUrl: "",
      note: "任务已完成，但未返回可用 artifact URL。",
    });
    return;
  }

  const rawArtifactUrl = String(glb.url || "").trim();
  const browserArtifactUrl = resolveArtifactUrl(rawArtifactUrl);

  if (/^https?:\/\//i.test(browserArtifactUrl)) {
    ensureTask(task.taskId, {
      resolvedArtifactUrl: browserArtifactUrl,
      rawArtifactUrl,
      note: rawArtifactUrl.startsWith("/")
        ? "artifact 使用相对路径返回，页面已按 API Base URL 自动补全。"
        : glb.expires_at
          ? "artifact 为临时 URL，过期后可刷新任务重新获取。"
          : task.note || "",
    });
    queueThumbnailGeneration(task.taskId, browserArtifactUrl);
    return;
  }

  if (!/^file:\/\//i.test(rawArtifactUrl)) {
    ensureTask(task.taskId, {
      resolvedArtifactUrl: browserArtifactUrl,
      rawArtifactUrl,
      note: "artifact URL 不是常见的 http(s) / file 协议，请按实际部署环境确认。",
    });
    return;
  }

  const candidates = buildLocalArtifactCandidates(task.taskId, rawArtifactUrl);
  for (const candidate of candidates) {
    const ok = await probeUrl(candidate);
    if (ok) {
      ensureTask(task.taskId, {
        resolvedArtifactUrl: candidate,
        rawArtifactUrl,
        note: "artifact 原始返回为 file://，页面已自动切换到可访问的同源地址。",
      });
      queueThumbnailGeneration(task.taskId, candidate);
      return;
    }
  }

  ensureTask(task.taskId, {
    resolvedArtifactUrl: rawArtifactUrl,
    rawArtifactUrl,
    note: "artifact 当前是 file:// 本地路径，浏览器通常无法直接预览；建议改用 MinIO presigned URL 或同源 HTTP 代理。",
  });
}

function queueThumbnailGeneration(taskId, url) {
  const task = state.tasks.get(taskId);
  if (!task || !isPreviewableUrl(url)) {
    return;
  }
  if (task.thumbnailUrl && task.thumbnailState === "ready") {
    return;
  }
  if (state.thumbnailCache.has(url)) {
    ensureTask(taskId, {
      thumbnailUrl: state.thumbnailCache.get(url),
      thumbnailState: "ready",
    });
    queueRender();
    return;
  }
  if (state.thumbnailJobs.has(url)) {
    ensureTask(taskId, { thumbnailState: "loading" });
    queueRender();
    return;
  }
  ensureTask(taskId, { thumbnailState: "loading" });
  const job = renderModelThumbnail(url, {
    width: 480,
    height: 320,
    background: "#09101f",
  })
    .then((dataUrl) => {
      state.thumbnailCache.set(url, dataUrl);
      for (const currentTask of state.tasks.values()) {
        if (currentTask.resolvedArtifactUrl === url) {
          ensureTask(currentTask.taskId, {
            thumbnailUrl: dataUrl,
            thumbnailState: "ready",
          });
        }
      }
      queueRender();
    })
    .catch((error) => {
      console.warn("thumbnail generation failed", error);
      for (const currentTask of state.tasks.values()) {
        if (currentTask.resolvedArtifactUrl === url) {
          ensureTask(currentTask.taskId, {
            thumbnailState: "failed",
          });
        }
      }
      queueRender();
    })
    .finally(() => {
      state.thumbnailJobs.delete(url);
    });
  state.thumbnailJobs.set(url, job);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("failed to read file"));
    reader.readAsDataURL(file);
  });
}

function clearSelectedFile({ keepStatus = false } = {}) {
  state.generate.file = null;
  state.generate.previewDataUrl = "";
  state.generate.uploadedUrl = "";
  state.generate.uploadId = "";
  state.generate.name = "";
  state.generate.uploadProgress = 0;
  if (!keepStatus) {
    state.generate.statusMessage = state.config.token
      ? "图片就绪后会自动上传，然后直接开始生成。"
      : "请先到设置页配置连接。";
    state.generate.statusTone = state.config.token ? "info" : "error";
  }
  queueRender();
}

async function handleFileSelection(file) {
  if (!file) {
    clearSelectedFile({ keepStatus: false });
    return;
  }
  const previewDataUrl = await readFileAsDataUrl(file);
  state.generate.file = file;
  state.generate.previewDataUrl = previewDataUrl;
  state.generate.uploadedUrl = "";
  state.generate.uploadId = "";
  state.generate.name = file.name;
  state.generate.statusMessage = state.config.token
    ? "图片已准备；提交后会自动上传并创建任务。"
    : "图片预览已就绪；请先配置 API Key。";
  state.generate.statusTone = state.config.token ? "info" : "error";
  queueRender();
}

function uploadFile(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", buildApiUrl("/v1/upload"));
    Object.entries(authHeaders(false)).forEach(([key, value]) => {
      xhr.setRequestHeader(key, value);
    });
    xhr.responseType = "json";

    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) {
        return;
      }
      const percent = Math.round((event.loaded / event.total) * 100);
      state.generate.uploadProgress = percent;
      state.generate.statusMessage = `正在上传图片：${percent}%`;
      state.generate.statusTone = "info";
      queueRender();
    });

    xhr.addEventListener("load", async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        state.authState = "configured";
        resolve(xhr.response || JSON.parse(xhr.responseText || "{}"));
        return;
      }
      try {
        const message = await parseUploadError(xhr);
        reject(new Error(message));
      } catch (error) {
        reject(error);
      }
    });

    xhr.addEventListener("error", () => {
      reject(new Error("上传失败，网络连接中断"));
    });

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

async function parseUploadError(xhr) {
  if (xhr.status === 401) {
    reportInvalidApiKey();
    return "API Key 无效或已停用";
  }
  const payload = xhr.response || (xhr.responseText ? JSON.parse(xhr.responseText) : null);
  if (payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  if (payload && payload.detail) {
    return JSON.stringify(payload.detail);
  }
  return `${xhr.status} ${xhr.statusText}`;
}

function requireConfig() {
  if (!state.config.baseUrl) {
    throw new Error("请先填写 API Base URL");
  }
  if (!state.config.token) {
    throw new Error("请先配置 API Key");
  }
}

async function ensureUploadedInput() {
  requireConfig();
  if (!state.generate.file) {
    throw new Error("请先选择一张输入图片");
  }
  if (state.generate.uploadedUrl) {
    return state.generate.uploadedUrl;
  }
  state.generate.isUploading = true;
  state.generate.uploadProgress = 0;
  setGenerateStatus("正在上传图片：0%", "info");
  try {
    const result = await uploadFile(state.generate.file);
    state.generate.uploadedUrl = result.url;
    state.generate.uploadId = result.uploadId || result.upload_id || "";
    state.generate.statusMessage = "上传完成，正在创建任务…";
    state.generate.statusTone = "success";
    return state.generate.uploadedUrl;
  } finally {
    state.generate.isUploading = false;
  }
}

async function submitNewTask({ imageUrl, previewDataUrl = state.generate.previewDataUrl } = {}) {
  requireConfig();
  const callbackUrl = String(state.generate.callbackUrl || "").trim();
  const payload = {
    type: "image_to_3d",
    image_url: imageUrl,
  };
  if (callbackUrl) {
    payload.callback_url = callbackUrl;
  }

  state.generate.isSubmitting = true;
  setGenerateStatus("正在创建任务…", "info");

  try {
    const response = await fetch(buildApiUrl("/v1/tasks"), {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await extractErrorMessage(response));
    }
    state.authState = "configured";

    const result = await response.json();
    const taskId = result.taskId;
    setCurrentTaskId(taskId);
    ensureTask(taskId, {
      status: String(result.status || "submitted"),
      statusLabel: formatTaskStatus(String(result.status || "submitted")),
      currentStage: String(result.status || "submitted"),
      progress: defaultProgressForStatus(String(result.status || "submitted")),
      queuePosition: result.queuePosition ?? null,
      estimatedWaitSeconds: result.estimatedWaitSeconds ?? null,
      estimatedFinishAt: result.estimatedFinishAt ?? null,
      model: result.model || "trellis",
      inputUrl: result.inputUrl || result.input_url || imageUrl,
      createdAt: new Date().toISOString(),
      submittedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      lastSeenAt: new Date().toISOString(),
      transport: "connecting",
      note: "任务已提交，正在连接实时进度流。",
      previewDataUrl,
      artifacts: [],
      events: [],
    });

    await refreshTaskList({ append: false, resubscribe: false, silent: true }).catch((error) => {
      console.warn("silent list refresh failed after submit", error);
    });
    subscribeToTask(taskId, { force: true }).catch((error) => {
      console.warn("background subscription failed after submit", error);
      showToast({ title: "实时连接失败", message: formatError(error), tone: "error" });
    });
    showToast({
      title: "任务已创建",
      message: `任务 ${getTaskShortId(taskId)} 已提交，正在建立实时连接。`,
      tone: "success",
    });
    return taskId;
  } finally {
    state.generate.isSubmitting = false;
    queueRender();
  }
}

async function submitGenerateFlow() {
  if (state.generate.isUploading || state.generate.isSubmitting) {
    return;
  }
  const imageUrl = await ensureUploadedInput();
  return submitNewTask({ imageUrl });
}

async function retryCurrentTask() {
  const task = getCurrentGenerateTask();
  if (!task?.inputUrl) {
    throw new Error("当前任务缺少 input_url，无法重试。请重新上传图片。");
  }
  return submitNewTask({
    imageUrl: task.inputUrl,
    previewDataUrl: task.previewDataUrl || state.generate.previewDataUrl,
  });
}

function resetGenerateFlow() {
  setCurrentTaskId("");
  clearSelectedFile({ keepStatus: false });
}

function formatError(error) {
  if (!error) {
    return "未知错误";
  }
  return error instanceof Error ? error.message : String(error);
}

async function extractErrorMessage(response) {
  if (response.status === 401) {
    reportInvalidApiKey();
    return "API Key 无效或已停用";
  }
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (payload.detail) {
      return JSON.stringify(payload.detail);
    }
    return JSON.stringify(payload);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

function reportInvalidApiKey() {
  state.authState = "invalid";
  updateConnectionUi();
  showToast({ title: "API Key 无效", message: "请到设置页更新 API Key。", tone: "error" });
}

async function pingReady({ silent = false } = {}) {
  persistConfig();
  try {
    const response = await fetch(buildApiUrl("/ready"), {
      headers: authHeaders(false),
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(await extractErrorMessage(response));
    }
    const payload = await response.json();
    setReadyState("ready", payload.status, `服务可用 · ${payload.service}`);
    if (!silent) {
      showToast({ title: "服务就绪", message: `已连接到 ${payload.service}。`, tone: "success" });
    }
    return payload;
  } catch (error) {
    setReadyState("error", "服务不可达", formatError(error));
    if (!silent) {
      showToast({ title: "服务检查失败", message: formatError(error), tone: "error" });
    }
    throw error;
  }
}

async function subscribeToTask(taskId, { force = false } = {}) {
  requireConfig();
  if (!force && state.subscriptions.has(taskId)) {
    return;
  }
  stopSubscription(taskId);
  ensureTask(taskId, {
    transport: "connecting",
    note: "正在连接实时进度流…",
  });
  try {
    await refreshTask(taskId, { silent: true });
  } catch (error) {
    console.warn("initial task refresh failed before SSE", error);
  }

  try {
    await connectSse(taskId);
  } catch (error) {
    console.warn("falling back to polling", error);
    ensureTask(taskId, {
      transport: "polling",
      note: "SSE 连接失败，已降级为每 3 秒轮询。",
    });
    startPolling(taskId);
  }
}

async function connectSse(taskId) {
  const controller = new AbortController();
  state.subscriptions.set(taskId, {
    mode: "sse",
    controller,
  });
  ensureTask(taskId, {
    transport: "sse",
    note: "SSE 已连接。",
  });

  const response = await fetch(buildApiUrl(`/v1/tasks/${encodeURIComponent(taskId)}/events`), {
    headers: authHeaders(false),
    signal: controller.signal,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`SSE 订阅失败：${await extractErrorMessage(response)}`);
  }
  if (!response.body || !response.body.getReader) {
    throw new Error("当前浏览器不支持 SSE 流式读取");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let reachedTerminal = false;

  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        break;
      }
      buffer += decoder.decode(chunk.value, { stream: true });
      const parts = buffer.replace(/\r/g, "").split("\n\n");
      buffer = parts.pop() || "";
      for (const rawBlock of parts) {
        const payload = parseSseEvent(rawBlock);
        if (!payload) {
          continue;
        }
        await applyEventPayload(taskId, payload, "sse");
        if (TERMINAL_STATUSES.has(payload.status)) {
          reachedTerminal = true;
        }
      }
    }

    const tail = parseSseEvent(buffer.replace(/\r/g, ""));
    if (tail) {
      await applyEventPayload(taskId, tail, "sse");
      if (TERMINAL_STATUSES.has(tail.status)) {
        reachedTerminal = true;
      }
    }
  } catch (error) {
    if (controller.signal.aborted) {
      return;
    }
    throw error;
  } finally {
    try {
      reader.releaseLock();
    } catch (error) {
      console.warn("failed to release SSE reader", error);
    }
  }

  const currentTask = state.tasks.get(taskId);
  if (reachedTerminal || (currentTask && TERMINAL_STATUSES.has(currentTask.status))) {
    ensureTask(taskId, {
      transport: "complete",
      note: currentTask?.note || "任务已进入终态。",
    });
    stopSubscription(taskId);
    return;
  }
  throw new Error("SSE 已断开，任务尚未结束");
}

function parseSseEvent(rawBlock) {
  if (!rawBlock.trim()) {
    return null;
  }
  let eventName = "";
  const dataLines = [];
  rawBlock.split("\n").forEach((line) => {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });
  if (!dataLines.length) {
    return null;
  }
  const payload = JSON.parse(dataLines.join("\n"));
  payload.event = payload.event || eventName;
  return payload;
}

function startPolling(taskId) {
  stopSubscription(taskId);
  const timer = window.setInterval(() => {
    refreshTask(taskId, { silent: true }).catch((error) => {
      console.warn("polling refresh failed", error);
      ensureTask(taskId, {
        transport: "polling",
        note: `轮询失败：${formatError(error)}`,
      });
      queueRender();
    });
  }, POLL_INTERVAL_MS);
  state.subscriptions.set(taskId, {
    mode: "polling",
    timer,
  });
}

function stopSubscription(taskId) {
  const current = state.subscriptions.get(taskId);
  if (!current) {
    return;
  }
  if (current.mode === "sse" && current.controller) {
    current.controller.abort();
  }
  if (current.mode === "polling" && current.timer) {
    window.clearInterval(current.timer);
  }
  state.subscriptions.delete(taskId);
}

async function restoreSubscriptions() {
  const tasks = Array.from(state.tasks.values()).sort(compareTaskRecords);
  for (const task of tasks) {
    if (!isActiveStatus(task.status)) {
      continue;
    }
    try {
      await subscribeToTask(task.taskId, { force: true });
    } catch (error) {
      ensureTask(task.taskId, {
        note: `恢复订阅失败：${formatError(error)}`,
      });
    }
  }
  queueRender();
}

async function cancelTask(taskId) {
  ensureTask(taskId, { pendingCancel: true });
  queueRender();
  try {
    const response = await fetch(buildApiUrl(`/v1/tasks/${encodeURIComponent(taskId)}/cancel`), {
      method: "POST",
      headers: authHeaders(false),
    });
    if (!response.ok) {
      throw new Error(await extractErrorMessage(response));
    }
    const payload = await response.json();
    await applyTaskSnapshot(taskId, payload, "snapshot");
    showToast({ title: "任务已取消", message: `任务 ${getTaskShortId(taskId)} 已进入 cancelled 状态。`, tone: "success" });
  } finally {
    const task = state.tasks.get(taskId);
    if (task) {
      ensureTask(taskId, { pendingCancel: false });
      queueRender();
    }
  }
}

async function deleteTask(taskId) {
  ensureTask(taskId, { pendingDelete: true });
  queueRender();
  const shouldRestoreGalleryFocus = state.route === "/gallery";
  try {
    const response = await fetch(buildApiUrl(`/v1/tasks/${encodeURIComponent(taskId)}`), {
      method: "DELETE",
      headers: authHeaders(false),
    });
    if (!response.ok) {
      throw new Error(await extractErrorMessage(response));
    }
    closeConfirm({ restoreFocus: false });
    removeTask(taskId);
    if (shouldRestoreGalleryFocus) {
      scheduleFocus(() => {
        const nextCard = elements.routeContent.querySelector('[data-action="open-drawer"]');
        if (nextCard instanceof HTMLElement) {
          nextCard.focus();
          return;
        }
        const fallback = elements.routeContent.querySelector("h1, h2, button, a");
        fallback?.focus?.();
      });
    }
    showToast({ title: "任务已删除", message: `任务 ${getTaskShortId(taskId)} 已从列表中移除。`, tone: "success" });
  } finally {
    const task = state.tasks.get(taskId);
    if (task) {
      ensureTask(taskId, { pendingDelete: false });
      queueRender();
    }
  }
}

function getCurrentGenerateTask() {
  return state.generate.currentTaskId ? state.tasks.get(state.generate.currentTaskId) || null : null;
}

function getGenerateView() {
  if (state.generate.isUploading || state.generate.isSubmitting) {
    return "uploading";
  }
  const task = getCurrentGenerateTask();
  if (!task) {
    return "idle";
  }
  if (task.status === "succeeded") {
    return "completed";
  }
  if (task.status === "failed" || task.status === "cancelled") {
    return "failed";
  }
  return "processing";
}

function renderRoute() {
  const helpers = {
    escapeHtml,
    formatTime,
    formatRelativeTime,
    formatTaskStatus,
    formatStage,
    buildStatusBadge,
    buildTaskThumbnail,
    buildLogFeed,
    getTaskShortId,
    getFilterCount,
  };

  if (state.route === "/gallery") {
    return renderGalleryPage({
      tasks: getFilteredTasks(),
      filter: state.galleryFilter,
      taskPage: state.taskPage,
      hasToken: Boolean(state.config.token),
      selectedTaskId: state.drawer.taskId,
      helpers,
    });
  }

  if (state.route === "/settings") {
    return renderSettingsPage({
      config: state.config,
      ready: state.ready,
      revealApiKey: state.settingsUi.revealApiKey,
      helpers,
    });
  }

  return renderGeneratePage({
    view: getGenerateView(),
    currentTask: getCurrentGenerateTask(),
    upload: state.generate,
    hasToken: Boolean(state.config.token),
    canCancel: isCancellable(getCurrentGenerateTask()),
    settingsReadyTone: state.ready.tone,
    helpers,
  });
}

function renderDrawer() {
  const task = state.drawer.taskId ? state.tasks.get(state.drawer.taskId) : null;
  elements.drawerBackdrop.hidden = !state.drawer.open;
  elements.drawerScroll.innerHTML = renderGalleryDrawer({
    task,
    canCancel: isCancellable(task),
    helpers: {
      escapeHtml,
      formatTime,
      formatTaskStatus,
      formatStage,
      buildStatusBadge,
      buildLogFeed,
      getTaskShortId,
    },
  });
  if (!elements.drawerBackdrop.hidden) {
    const closeButton = elements.drawerScroll.querySelector('[data-action="close-drawer"]');
    if (closeButton && document.activeElement === document.body) {
      window.requestAnimationFrame(() => closeButton.focus());
    }
  }
}

function renderConfirm() {
  if (!state.confirm) {
    elements.confirmModal.hidden = true;
    elements.confirmTitle.textContent = "确认继续？";
    elements.confirmCopy.textContent = "";
    elements.confirmAcceptButton.textContent = "确认";
    elements.confirmAcceptButton.className = "pill-button rounded-full bg-rose-500 px-4 py-2.5 text-sm font-semibold text-white";
    return;
  }

  elements.confirmModal.hidden = false;
  elements.confirmTitle.textContent = state.confirm.title;
  elements.confirmCopy.textContent = state.confirm.copy;
  elements.confirmAcceptButton.textContent = state.confirm.confirmLabel;
  elements.confirmAcceptButton.disabled = Boolean(state.confirm.busy);
  elements.confirmAcceptButton.className = state.confirm.tone === "danger"
    ? "pill-button rounded-full bg-rose-500 px-4 py-2.5 text-sm font-semibold text-white"
    : "pill-button rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-slate-950";
}

function updateOverlayInertState() {
  elements.appShell.inert = Boolean(state.drawer.open || state.confirm);
  elements.drawerSurface.inert = Boolean(state.confirm);
}

function updateNavUi() {
  document.querySelectorAll('[data-nav-path]').forEach((link) => {
    link.classList.toggle('is-active', link.dataset.navPath === state.route);
  });
  const expanded = !elements.mobileNavPanel.hidden;
  elements.mobileNavButton.setAttribute('aria-expanded', expanded ? 'true' : 'false');
}

function disposeViewer(viewerName) {
  const viewer = state.viewers[viewerName];
  if (viewer) {
    viewer.dispose();
    state.viewers[viewerName] = null;
  }
}

function ensureViewer(viewerName, containerId, background) {
  const container = document.getElementById(containerId);
  if (!container) {
    disposeViewer(viewerName);
    return null;
  }
  const currentViewer = state.viewers[viewerName];
  if (currentViewer && currentViewer.container === container) {
    return currentViewer;
  }
  disposeViewer(viewerName);
  if (viewerName === "drawer") {
    state.drawer.lastViewerKey = "";
  }
  if (viewerName === "generate") {
    state.generate.viewerKey = "";
  }
  const nextViewer = new Viewer3D(container, { background });
  state.viewers[viewerName] = nextViewer;
  return nextViewer;
}

async function syncGenerateViewer() {
  if (state.route !== "/" || getGenerateView() !== "completed") {
    disposeViewer("generate");
    state.generate.viewerKey = "";
    return;
  }
  const task = getCurrentGenerateTask();
  const viewer = ensureViewer("generate", "generate-viewer", "#050816");
  if (!viewer || !task) {
    return;
  }
  const previewUrl = task.resolvedArtifactUrl || "";
  const nextKey = isPreviewableUrl(previewUrl)
    ? previewUrl
    : `message:${task.status}:${task.note || ""}:${task.error?.message || ""}`;
  if (state.generate.viewerKey === nextKey) {
    return;
  }
  state.generate.viewerKey = nextKey;
  try {
    if (isPreviewableUrl(previewUrl)) {
      await viewer.load(previewUrl);
      return;
    }
    viewer.setMessage("当前 artifact 地址无法直接在浏览器中预览。", "error");
  } catch (error) {
    viewer.setMessage("3D 模型加载失败", "error");
    showToast({ title: "预览加载失败", message: formatError(error), tone: "error" });
  }
}

async function syncDrawerViewer() {
  if (!state.drawer.open) {
    disposeViewer("drawer");
    state.drawer.lastViewerKey = "";
    return;
  }
  const task = state.drawer.taskId ? state.tasks.get(state.drawer.taskId) : null;
  const viewer = ensureViewer("drawer", "drawer-viewer", "#050816");
  if (!viewer || !task) {
    return;
  }
  const previewUrl = task.resolvedArtifactUrl || "";
  const nextKey = isPreviewableUrl(previewUrl)
    ? previewUrl
    : `message:${task.status}:${task.note || ""}:${task.error?.message || ""}`;
  if (state.drawer.lastViewerKey === nextKey) {
    return;
  }
  state.drawer.lastViewerKey = nextKey;

  try {
    if (isPreviewableUrl(previewUrl)) {
      await viewer.load(previewUrl);
      return;
    }
    if (task.status !== "succeeded") {
      viewer.setMessage("任务完成后，会在这里自动加载 3D 预览。", "info");
      return;
    }
    viewer.setMessage("当前 artifact 地址无法直接在浏览器中预览。", "error");
  } catch (error) {
    viewer.setMessage("3D 模型加载失败", "error");
    showToast({ title: "预览加载失败", message: formatError(error), tone: "error" });
  }
}

async function renderApp() {
  elements.routeContent.innerHTML = renderRoute();
  renderDrawer();
  renderConfirm();
  updateOverlayInertState();
  updateNavUi();
  updateConnectionUi();
  refreshIcons();
  await Promise.all([syncGenerateViewer(), syncDrawerViewer()]);
  flushPendingFocus();
}

function showToast({ title, message, tone = "info", duration = 3200 }) {
  const toast = document.createElement("div");
  toast.className = `toast ${tone}`;
  toast.innerHTML = `
    <div class="toast-title">${escapeHtml(title)}</div>
    <div class="toast-copy">${escapeHtml(message)}</div>
  `;
  elements.toastStack.appendChild(toast);
  window.setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px) scale(0.98)";
    window.setTimeout(() => toast.remove(), 180);
  }, duration);
}

function requestDrawerViewerSync() {
  window.requestAnimationFrame(() => {
    syncDrawerViewer().catch((error) => {
      console.warn("drawer viewer sync failed", error);
    });
  });
}

function openDrawer(taskId, trigger = document.activeElement) {
  state.drawer.open = true;
  state.drawer.taskId = taskId;
  state.drawer.trigger = trigger instanceof HTMLElement ? trigger : null;
  state.drawer.lastViewerKey = "";
  queueRender();
  requestDrawerViewerSync();
  refreshTask(taskId, { silent: true }).catch((error) => {
    console.warn("drawer refresh failed", error);
  }).finally(() => {
    requestDrawerViewerSync();
  });
  const task = state.tasks.get(taskId);
  if (task && isActiveStatus(task.status)) {
    subscribeToTask(taskId, { force: true }).catch((error) => {
      console.warn("drawer subscription restore failed", error);
    });
  }
}

function closeDrawer({ restoreFocus = true } = {}) {
  const fallbackTrigger = state.drawer.trigger;
  state.drawer.open = false;
  state.drawer.taskId = "";
  state.drawer.lastViewerKey = "";
  state.drawer.trigger = null;
  queueRender();
  if (restoreFocus) {
    scheduleFocus(() => {
      if (fallbackTrigger && fallbackTrigger.isConnected) {
        fallbackTrigger.focus();
        return;
      }
      const heading = elements.routeContent.querySelector("h1, h2, button, a");
      heading?.focus?.();
    });
  }
}

function openConfirm({ title, copy, confirmLabel = "确认", tone = "danger", onAccept, trigger }) {
  state.confirm = {
    title,
    copy,
    confirmLabel,
    tone,
    onAccept,
    trigger: trigger instanceof HTMLElement ? trigger : document.activeElement instanceof HTMLElement ? document.activeElement : null,
    busy: false,
  };
  queueRender();
  scheduleFocus(() => {
    elements.confirmCancelButton.focus();
  });
}

function closeConfirm({ restoreFocus = true } = {}) {
  const previous = state.confirm;
  state.confirm = null;
  queueRender();
  if (restoreFocus && previous?.trigger) {
    scheduleFocus(() => {
      if (previous.trigger && previous.trigger.isConnected) {
        previous.trigger.focus();
      }
    });
  }
}

async function acceptConfirm() {
  const current = state.confirm;
  if (!current || typeof current.onAccept !== "function") {
    closeConfirm();
    return;
  }
  state.confirm.busy = true;
  queueRender();
  closeConfirm({ restoreFocus: false });
  await current.onAccept();
}

function parseRouteFromHash() {
  const normalized = (window.location.hash || "#/" ).replace(/^#/, "") || "/";
  return ROUTES.has(normalized) ? normalized : "/";
}

function navigateToHash(hashPath) {
  if ((window.location.hash || "") === `#${hashPath}`) {
    handleHashChange();
    return;
  }
  window.location.hash = `#${hashPath}`;
}

function handleHashChange() {
  const nextRoute = parseRouteFromHash();
  state.route = nextRoute;
  if (nextRoute !== "/gallery" && state.drawer.open) {
    closeDrawer({ restoreFocus: false });
  }
  elements.mobileNavPanel.hidden = true;
  queueRender();
}

async function handleGenerateSubmit(event) {
  event.preventDefault();
  try {
    await submitGenerateFlow();
  } catch (error) {
    setGenerateStatus(formatError(error), "error");
    showToast({ title: "提交失败", message: formatError(error), tone: "error" });
  }
}

function handleRouteClick(event) {
  const dropzone = event.target.closest?.("#generate-dropzone");
  if (
    dropzone &&
    !event.target.closest("[data-action]") &&
    !event.target.closest("button, a, input, label")
  ) {
    const input = document.getElementById("generate-file-input");
    input?.click();
    return;
  }

  const target = event.target.closest("[data-action]");
  if (!target) {
    return;
  }
  const { action } = target.dataset;

  if (action === "open-file-dialog") {
    const input = document.getElementById("generate-file-input");
    input?.click();
    return;
  }

  if (action === "clear-selected-file") {
    clearSelectedFile({ keepStatus: false });
    return;
  }

  if (action === "cancel-current-task") {
    const task = getCurrentGenerateTask();
    if (!task) {
      return;
    }
    cancelTask(task.taskId).catch((error) => {
      showToast({ title: "取消失败", message: formatError(error), tone: "error" });
    });
    return;
  }

  if (action === "retry-current-task") {
    retryCurrentTask().catch((error) => {
      showToast({ title: "重试失败", message: formatError(error), tone: "error" });
    });
    return;
  }

  if (action === "reset-generate-flow") {
    resetGenerateFlow();
    return;
  }

  if (action === "set-gallery-filter") {
    state.galleryFilter = target.dataset.filter || "all";
    queueRender();
    return;
  }

  if (action === "open-drawer") {
    const taskId = target.dataset.taskId;
    if (!taskId) {
      return;
    }
    openDrawer(taskId, target);
    return;
  }

  if (action === "close-drawer") {
    closeDrawer();
    return;
  }

  if (action === "refresh-drawer-task") {
    if (!state.drawer.taskId) {
      return;
    }
    refreshTask(state.drawer.taskId, { silent: false }).catch((error) => {
      showToast({ title: "刷新失败", message: formatError(error), tone: "error" });
    });
    return;
  }

  if (action === "cancel-drawer-task") {
    if (!state.drawer.taskId) {
      return;
    }
    cancelTask(state.drawer.taskId).catch((error) => {
      showToast({ title: "取消失败", message: formatError(error), tone: "error" });
    });
    return;
  }

  if (action === "delete-drawer-task") {
    if (!state.drawer.taskId) {
      return;
    }
    const taskId = state.drawer.taskId;
    openConfirm({
      title: "删除当前任务？",
      copy: `任务 ${getTaskShortId(taskId)} 将从图库实时移除，并触发后端 artifact 清理。`,
      confirmLabel: "删除任务",
      tone: "danger",
      trigger: target,
      onAccept: async () => {
        await deleteTask(taskId);
      },
    });
    return;
  }

  if (action === "load-more-tasks") {
    refreshTaskList({ append: true, resubscribe: false, silent: false }).catch((error) => {
      showToast({ title: "加载失败", message: formatError(error), tone: "error" });
    });
    return;
  }

  if (action === "toggle-api-key-visibility") {
    state.settingsUi.revealApiKey = !state.settingsUi.revealApiKey;
    queueRender();
    return;
  }

  if (action === "test-ready") {
    const baseUrlInput = document.getElementById("settings-base-url");
    const apiKeyInput = document.getElementById("settings-api-key");
    persistConfig({
      baseUrl: baseUrlInput?.value || state.config.baseUrl,
      token: apiKeyInput?.value || state.config.token,
    });
    pingReady({ silent: false }).catch(() => {});
  }
}

function handleRouteChange(event) {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) {
    return;
  }
  if (input.id === "generate-file-input") {
    const [file] = input.files || [];
    handleFileSelection(file).catch((error) => {
      setGenerateStatus(formatError(error), "error");
    });
    return;
  }
  if (input.id === "generate-callback-url") {
    state.generate.callbackUrl = input.value;
  }
}

function handleRouteInput(event) {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) {
    return;
  }
  if (input.id === "generate-callback-url") {
    state.generate.callbackUrl = input.value;
  }
}

function handleDragEvents(event) {
  const dropzone = event.target.closest?.("#generate-dropzone");
  if (!dropzone) {
    return;
  }
  if (event.type === "dragenter" || event.type === "dragover") {
    event.preventDefault();
    dropzone.classList.add("dragover");
    return;
  }
  if (event.type === "dragleave" || event.type === "dragend") {
    dropzone.classList.remove("dragover");
    return;
  }
  if (event.type === "drop") {
    event.preventDefault();
    dropzone.classList.remove("dragover");
    const [file] = event.dataTransfer?.files || [];
    handleFileSelection(file).catch((error) => {
      setGenerateStatus(formatError(error), "error");
    });
  }
}

function handleRouteKeydown(event) {
  if (event.key === "Escape") {
    if (state.confirm) {
      closeConfirm();
      return;
    }
    if (state.drawer.open) {
      closeDrawer();
      return;
    }
  }

  if ((event.key === "Enter" || event.key === " ") && event.target.id === "generate-dropzone") {
    event.preventDefault();
    const input = document.getElementById("generate-file-input");
    input?.click();
  }
}

function handleRouteSubmit(event) {
  if (event.target.id === "generate-form") {
    handleGenerateSubmit(event);
    return;
  }
  if (event.target.id === "settings-form") {
    event.preventDefault();
    const baseUrlInput = document.getElementById("settings-base-url");
    const apiKeyInput = document.getElementById("settings-api-key");
    persistConfig({
      baseUrl: baseUrlInput?.value || state.config.baseUrl,
      token: apiKeyInput?.value || state.config.token,
    });
    Promise.allSettled([
      pingReady({ silent: true }),
      refreshTaskList({ append: false, resubscribe: true, silent: true }),
    ]).then((results) => {
      const refreshTaskResult = results[1];
      const refreshFailed = refreshTaskResult.status === "rejected";
      showToast({
        title: "配置已保存",
        message: refreshFailed
          ? `API Key 与 Base URL 已更新，但任务列表刷新失败：${formatError(refreshTaskResult.reason)}`
          : "API Key 与 Base URL 已更新。",
        tone: refreshFailed ? "info" : "success",
      });
    });
  }
}

function registerEventHandlers() {
  elements.mobileNavButton.addEventListener("click", () => {
    elements.mobileNavPanel.hidden = !elements.mobileNavPanel.hidden;
    updateNavUi();
  });
  elements.routeContent.addEventListener("click", handleRouteClick);
  elements.drawerScroll.addEventListener("click", handleRouteClick);
  elements.routeContent.addEventListener("change", handleRouteChange);
  elements.routeContent.addEventListener("input", handleRouteInput);
  elements.routeContent.addEventListener("submit", handleRouteSubmit);
  elements.routeContent.addEventListener("keydown", handleRouteKeydown);
  ["dragenter", "dragover", "dragleave", "dragend", "drop"].forEach((eventName) => {
    elements.routeContent.addEventListener(eventName, handleDragEvents);
  });

  elements.drawerBackdrop.addEventListener("click", (event) => {
    if (event.target === elements.drawerBackdrop) {
      closeDrawer();
    }
  });

  elements.confirmModal.addEventListener("click", (event) => {
    if (event.target === elements.confirmModal) {
      closeConfirm();
    }
  });
  elements.confirmCancelButton.addEventListener("click", () => closeConfirm());
  elements.confirmAcceptButton.addEventListener("click", () => {
    acceptConfirm().catch((error) => {
      showToast({ title: "操作失败", message: formatError(error), tone: "error" });
    });
  });

  window.addEventListener("hashchange", handleHashChange);
  window.addEventListener("beforeunload", () => {
    Array.from(state.subscriptions.keys()).forEach((taskId) => stopSubscription(taskId));
    disposeViewer("generate");
    disposeViewer("drawer");
  });
}

async function bootstrap() {
  loadConfig();
  updateConnectionUi();
  state.route = parseRouteFromHash();
  if (!window.location.hash) {
    window.location.hash = "#/";
    state.route = "/";
  }
  if (!state.generate.statusMessage) {
    state.generate.statusMessage = state.config.token
      ? "图片就绪后会自动上传，然后直接开始生成。"
      : "请先到设置页配置连接。";
    state.generate.statusTone = state.config.token ? "info" : "error";
  }
  registerEventHandlers();
  queueRender();
  if (state.config.baseUrl) {
    pingReady({ silent: true }).catch(() => {});
  }
  if (state.config.baseUrl && state.config.token) {
    refreshTaskList({ append: false, resubscribe: true, silent: true }).catch((error) => {
      showToast({ title: "加载任务失败", message: formatError(error), tone: "error" });
    });
  }
}

bootstrap();
