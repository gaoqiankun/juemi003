import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import {
  authHeaders,
  buildApiUrl,
  createTask,
  extractErrorMessage,
  fetchHealth,
  fetchTask,
  fetchTaskList,
  getDefaultBaseUrl,
  normalizeBaseUrl,
  requestTaskCancel,
  requestTaskDelete,
  uploadFile,
} from "@/lib/api";
import {
  ACTIVE_STATUSES,
  CANCELLABLE_STATUSES,
  compareTaskRecords,
  defaultProgressForStatus,
  formatTaskStatus,
  TERMINAL_STATUSES,
} from "@/lib/format";
import { renderModelThumbnail } from "@/lib/viewer";
import { readFileAsDataUrl } from "@/lib/utils";
import type {
  ApiConfig,
  ArtifactPayload,
  ConnectionState,
  GalleryFilter,
  GenerateState,
  GenerateView,
  HealthPayload,
  TaskCreatePayload,
  TaskEventRecord,
  TaskListPayload,
  TaskPageState,
  TaskRecord,
  TaskSnapshotPayload,
  TaskStatus,
  TaskSummaryPayload,
} from "@/lib/types";

const STORAGE_KEYS = {
  config: "gen3d.react.config.v1",
  currentTask: "gen3d.react.current-task.v1",
};
const TASK_PAGE_LIMIT = 20;
const POLL_INTERVAL_MS = 3000;

const defaultConnectionState: ConnectionState = {
  tone: "error",
  label: "连接未检测",
  detail: "保存配置后使用 /health 检测服务状态。",
};

const defaultGenerateState = (token = "", currentTaskId = ""): GenerateState => ({
  file: null,
  previewDataUrl: "",
  uploadedUrl: "",
  uploadId: "",
  name: "",
  callbackUrl: "",
  isUploading: false,
  uploadProgress: 0,
  isSubmitting: false,
  statusMessage: token
    ? "图片就绪后会自动上传，然后直接开始生成。"
    : "请先到设置页配置连接。",
  statusTone: token ? "info" : "error",
  currentTaskId,
});

function readStoredCurrentTaskId() {
  try {
    return String(sessionStorage.getItem(STORAGE_KEYS.currentTask) || "").trim();
  } catch {
    return "";
  }
}

function readStoredConfig(): ApiConfig {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEYS.config) || "{}");
    return {
      baseUrl: normalizeBaseUrl(saved.baseUrl || getDefaultBaseUrl()),
      token: String(saved.token || "").trim(),
    };
  } catch {
    return {
      baseUrl: getDefaultBaseUrl(),
      token: "",
    };
  }
}

function isPreviewableUrl(url?: string | null) {
  return /^https?:\/\//i.test(String(url || ""));
}

function isActiveStatus(status?: string): status is TaskStatus {
  return ACTIVE_STATUSES.has((status || "") as TaskStatus);
}

function normalizeTaskRecord(task: Partial<TaskRecord> & Record<string, any>): TaskRecord {
  const taskId = String(task.taskId || task.task_id || "").trim();
  const status = String(task.status || task.statusLabel || task.status_label || "submitted") as TaskStatus;
  const createdAt = String(task.createdAt || task.created_at || task.submittedAt || task.submitted_at || new Date().toISOString());
  const updatedAt = String(task.updatedAt || task.updated_at || task.finishedAt || task.finished_at || createdAt);
  const artifacts = Array.isArray(task.artifacts) ? (task.artifacts as ArtifactPayload[]) : [];
  return {
    taskId,
    model: String(task.model || "trellis"),
    inputUrl: String(task.inputUrl || task.input_url || ""),
    createdAt,
    submittedAt: String(task.submittedAt || task.submitted_at || createdAt),
    updatedAt,
    lastSeenAt: String(task.lastSeenAt || task.last_seen_at || updatedAt),
    status,
    statusLabel: String(task.statusLabel || task.status_label || formatTaskStatus(status)),
    progress: Number.isFinite(task.progress) ? Number(task.progress) : defaultProgressForStatus(status),
    currentStage: String(task.currentStage || task.current_stage || status),
    queuePosition: task.queuePosition ?? task.queue_position ?? null,
    estimatedWaitSeconds: task.estimatedWaitSeconds ?? task.estimated_wait_seconds ?? null,
    estimatedFinishAt: task.estimatedFinishAt || task.estimated_finish_at || null,
    artifacts,
    error: task.error || null,
    events: Array.isArray(task.events) ? (task.events as TaskEventRecord[]).slice(-30) : [],
    transport: String(task.transport || "idle"),
    note: String(task.note || ""),
    resolvedArtifactUrl: String(task.resolvedArtifactUrl || task.resolved_artifact_url || ""),
    rawArtifactUrl: String(task.rawArtifactUrl || task.raw_artifact_url || ""),
    previewDataUrl: String(task.previewDataUrl || task.preview_data_url || ""),
    thumbnailUrl: String(task.thumbnailUrl || task.thumbnail_url || ""),
    thumbnailState: (task.thumbnailState || task.thumbnail_state || "idle") as TaskRecord["thumbnailState"],
    pendingDelete: Boolean(task.pendingDelete),
    pendingCancel: Boolean(task.pendingCancel),
    successRefreshScheduled: Boolean(task.successRefreshScheduled),
  };
}

interface SubscriptionHandle {
  mode: "sse" | "polling";
  controller?: AbortController;
  timer?: number;
}

interface Gen3dContextValue {
  config: ApiConfig;
  connection: ConnectionState;
  tasks: TaskRecord[];
  taskMap: Record<string, TaskRecord>;
  taskPage: TaskPageState;
  generate: GenerateState;
  currentTask: TaskRecord | null;
  generateView: GenerateView;
  galleryFilter: GalleryFilter;
  setGalleryFilter: (filter: GalleryFilter) => void;
  getFilteredTasks: (filter?: GalleryFilter) => TaskRecord[];
  saveConfig: (next: Partial<ApiConfig>) => Promise<void>;
  pingHealth: (silent?: boolean) => Promise<HealthPayload>;
  refreshTaskList: (options?: { append?: boolean; resubscribe?: boolean; silent?: boolean }) => Promise<void>;
  refreshTask: (taskId: string, options?: { silent?: boolean }) => Promise<void>;
  selectFile: (file: File | null) => Promise<void>;
  clearSelectedFile: (keepStatus?: boolean) => void;
  submitCurrentFile: () => Promise<string | undefined>;
  retryCurrentTask: () => Promise<string | undefined>;
  cancelTask: (taskId: string) => Promise<void>;
  deleteTask: (taskId: string) => Promise<void>;
  subscribeToTask: (taskId: string, force?: boolean) => Promise<void>;
  setCurrentTaskId: (taskId: string) => void;
}

const Gen3dContext = createContext<Gen3dContextValue | null>(null);

export function Gen3dProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<ApiConfig>(() => readStoredConfig());
  const [connection, setConnection] = useState<ConnectionState>(defaultConnectionState);
  const [tasks, setTasks] = useState<Record<string, TaskRecord>>({});
  const [taskPage, setTaskPage] = useState<TaskPageState>({
    limit: TASK_PAGE_LIMIT,
    nextCursor: "",
    hasMore: false,
    isLoading: false,
  });
  const [galleryFilter, setGalleryFilter] = useState<GalleryFilter>("all");
  const [generate, setGenerate] = useState<GenerateState>(() => defaultGenerateState(readStoredConfig().token, readStoredCurrentTaskId()));

  const configRef = useRef(config);
  const tasksRef = useRef(tasks);
  const taskPageRef = useRef(taskPage);
  const generateRef = useRef(generate);
  const subscriptionsRef = useRef<Map<string, SubscriptionHandle>>(new Map());
  const thumbnailCacheRef = useRef<Map<string, string>>(new Map());
  const thumbnailJobsRef = useRef<Map<string, Promise<void>>>(new Map());

  useEffect(() => {
    configRef.current = config;
  }, [config]);
  useEffect(() => {
    tasksRef.current = tasks;
  }, [tasks]);
  useEffect(() => {
    taskPageRef.current = taskPage;
  }, [taskPage]);
  useEffect(() => {
    generateRef.current = generate;
    try {
      if (generate.currentTaskId) {
        sessionStorage.setItem(STORAGE_KEYS.currentTask, generate.currentTaskId);
      } else {
        sessionStorage.removeItem(STORAGE_KEYS.currentTask);
      }
    } catch {
      // ignore private mode storage errors
    }
  }, [generate]);

  const updateTasks = useCallback((updater: (previous: Record<string, TaskRecord>) => Record<string, TaskRecord>) => {
    setTasks((previous) => {
      const next = updater(previous);
      tasksRef.current = next;
      return next;
    });
  }, []);

  const updateTaskPage = useCallback((updater: (previous: TaskPageState) => TaskPageState) => {
    setTaskPage((previous) => {
      const next = updater(previous);
      taskPageRef.current = next;
      return next;
    });
  }, []);

  const persistConfig = useCallback((next: Partial<ApiConfig>) => {
    setConfig((previous) => {
      const merged = {
        baseUrl: normalizeBaseUrl(next.baseUrl ?? previous.baseUrl),
        token: String(next.token ?? previous.token).trim(),
      };
      try {
        localStorage.setItem(STORAGE_KEYS.config, JSON.stringify(merged));
      } catch {
        // ignore storage failures
      }
      return merged;
    });
  }, []);

  const setCurrentTaskId = useCallback((taskId: string) => {
    setGenerate((previous) => ({
      ...previous,
      currentTaskId: taskId,
    }));
  }, []);

  const setGenerateStatus = useCallback((message: string, tone: GenerateState["statusTone"] = "info") => {
    setGenerate((previous) => ({
      ...previous,
      statusMessage: message,
      statusTone: tone,
    }));
  }, []);

  const upsertTask = useCallback((taskId: string, patch: Record<string, unknown>) => {
    let nextTask: TaskRecord | null = null;
    updateTasks((previous) => {
      const merged = normalizeTaskRecord({
        ...(previous[taskId] || { taskId }),
        ...patch,
        taskId,
      });
      nextTask = merged;
      return {
        ...previous,
        [taskId]: merged,
      };
    });
    return nextTask ?? normalizeTaskRecord({ taskId });
  }, [updateTasks]);

  const stopSubscription = useCallback((taskId: string) => {
    const current = subscriptionsRef.current.get(taskId);
    if (!current) {
      return;
    }
    if (current.mode === "sse") {
      current.controller?.abort();
    }
    if (current.mode === "polling" && typeof current.timer === "number") {
      window.clearInterval(current.timer);
    }
    subscriptionsRef.current.delete(taskId);
  }, []);

  const removeTask = useCallback((taskId: string) => {
    stopSubscription(taskId);
    updateTasks((previous) => {
      if (!previous[taskId]) {
        return previous;
      }
      const next = { ...previous };
      delete next[taskId];
      return next;
    });
    if (generateRef.current.currentTaskId === taskId) {
      setGenerate((previous) => ({
        ...defaultGenerateState(configRef.current.token, ""),
        callbackUrl: previous.callbackUrl,
      }));
    }
  }, [stopSubscription, updateTasks]);

  const resetTaskState = useCallback(() => {
    Array.from(subscriptionsRef.current.keys()).forEach((taskId) => stopSubscription(taskId));
    updateTasks(() => ({}));
    updateTaskPage(() => ({
      limit: TASK_PAGE_LIMIT,
      nextCursor: "",
      hasMore: false,
      isLoading: false,
    }));
    setCurrentTaskId("");
  }, [setCurrentTaskId, stopSubscription, updateTaskPage, updateTasks]);

  const syncCurrentTaskSelection = useCallback((nextTasks: Record<string, TaskRecord>) => {
    const currentTaskId = generateRef.current.currentTaskId;
    if (currentTaskId && nextTasks[currentTaskId]) {
      return;
    }
    const latestActive = Object.values(nextTasks)
      .filter((task) => isActiveStatus(task.status))
      .sort(compareTaskRecords)[0];
    if (latestActive) {
      setCurrentTaskId(latestActive.taskId);
      return;
    }
    if (currentTaskId && !nextTasks[currentTaskId]) {
      setCurrentTaskId("");
    }
  }, [setCurrentTaskId]);

  const resolveArtifactUrl = useCallback((url?: string | null) => {
    const raw = String(url || "").trim();
    if (!raw) {
      return "";
    }
    if (raw.startsWith("/")) {
      return buildApiUrl(configRef.current.baseUrl, raw);
    }
    return raw;
  }, []);

  const buildLocalArtifactCandidates = useCallback((taskId: string, fileUrl: string) => {
    let fileName = "model.glb";
    try {
      const path = decodeURIComponent(new URL(fileUrl).pathname);
      const parts = path.split("/").filter(Boolean);
      fileName = parts[parts.length - 1] || fileName;
    } catch {
      // ignore malformed file paths
    }
    const root = `${configRef.current.baseUrl.replace(/\/+$/, "")}/`;
    return Array.from(new Set([
      new URL(`artifacts/${encodeURIComponent(taskId)}/${encodeURIComponent(fileName)}`, root).toString(),
      new URL(`v1/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(fileName)}`, root).toString(),
      new URL(`${encodeURIComponent(taskId)}/${encodeURIComponent(fileName)}`, new URL("artifacts/", root)).toString(),
    ]));
  }, []);

  const probeUrl = useCallback(async (url: string) => {
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
  }, []);

  const getArtifactRequestHeaders = useCallback((url: string): Record<string, string> => {
    const token = configRef.current.token;
    if (!token) {
      return {};
    }
    try {
      const resource = new URL(url);
      const apiRoot = new URL(configRef.current.baseUrl);
      if (resource.origin !== apiRoot.origin) {
        return {};
      }
      return {
        Authorization: `Bearer ${token}`,
      };
    } catch {
      return {};
    }
  }, []);

  const queueThumbnailGeneration = useCallback((taskId: string, url: string) => {
    if (!isPreviewableUrl(url)) {
      return;
    }
    const currentTask = tasksRef.current[taskId];
    if (!currentTask) {
      return;
    }
    if (currentTask.thumbnailUrl && currentTask.thumbnailState === "ready") {
      return;
    }
    const cached = thumbnailCacheRef.current.get(url);
    if (cached) {
      upsertTask(taskId, {
        thumbnailUrl: cached,
        thumbnailState: "ready",
      });
      return;
    }
    if (thumbnailJobsRef.current.has(url)) {
      upsertTask(taskId, { thumbnailState: "loading" });
      return;
    }
    upsertTask(taskId, { thumbnailState: "loading" });
    const job = renderModelThumbnail(url, {
      width: 480,
      height: 320,
      background: "#09101f",
      requestHeaders: getArtifactRequestHeaders(url),
    })
      .then((dataUrl) => {
        thumbnailCacheRef.current.set(url, dataUrl);
        updateTasks((previous) => {
          const next = { ...previous };
          Object.values(next).forEach((task) => {
            if (task.resolvedArtifactUrl === url) {
              next[task.taskId] = normalizeTaskRecord({
                ...task,
                thumbnailUrl: dataUrl,
                thumbnailState: "ready",
              });
            }
          });
          return next;
        });
      })
      .catch((error) => {
        console.warn("thumbnail generation failed", error);
        updateTasks((previous) => {
          const next = { ...previous };
          Object.values(next).forEach((task) => {
            if (task.resolvedArtifactUrl === url) {
              next[task.taskId] = normalizeTaskRecord({
                ...task,
                thumbnailState: "failed",
              });
            }
          });
          return next;
        });
      })
      .finally(() => {
        thumbnailJobsRef.current.delete(url);
      });
    thumbnailJobsRef.current.set(url, job);
  }, [getArtifactRequestHeaders, updateTasks, upsertTask]);

  const hydrateArtifact = useCallback(async (task: TaskRecord) => {
    if (task.status !== "succeeded" || !Array.isArray(task.artifacts) || task.artifacts.length === 0) {
      upsertTask(task.taskId, {
        resolvedArtifactUrl: "",
        rawArtifactUrl: task.rawArtifactUrl || "",
      });
      return;
    }

    const glb = task.artifacts.find((artifact) => artifact.type === "glb") || task.artifacts[0];
    if (!glb || !glb.url) {
      upsertTask(task.taskId, {
        resolvedArtifactUrl: "",
        note: "任务已完成，但未返回可用 artifact URL。",
      });
      return;
    }

    const rawArtifactUrl = String(glb.url || "").trim();
    const browserArtifactUrl = resolveArtifactUrl(rawArtifactUrl);

    if (/^https?:\/\//i.test(browserArtifactUrl)) {
      upsertTask(task.taskId, {
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
      upsertTask(task.taskId, {
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
        upsertTask(task.taskId, {
          resolvedArtifactUrl: candidate,
          rawArtifactUrl,
          note: "artifact 原始返回为 file://，页面已自动切换到可访问的同源地址。",
        });
        queueThumbnailGeneration(task.taskId, candidate);
        return;
      }
    }

    upsertTask(task.taskId, {
      resolvedArtifactUrl: rawArtifactUrl,
      rawArtifactUrl,
      note: "artifact 当前是 file:// 本地路径，浏览器通常无法直接预览；建议改用 MinIO presigned URL 或同源 HTTP 代理。",
    });
  }, [buildLocalArtifactCandidates, probeUrl, queueThumbnailGeneration, resolveArtifactUrl, upsertTask]);

  const appendTaskEvent = useCallback((taskId: string, payload: Record<string, any>, source: string) => {
    updateTasks((previous) => {
      const task = previous[taskId];
      if (!task) {
        return previous;
      }
      const eventEntry: TaskEventRecord = {
        event: String(payload.event || payload.status || source),
        status: String(payload.status || task.status),
        progress: Number.isFinite(payload.progress) ? Number(payload.progress) : task.progress,
        currentStage: String(payload.currentStage || payload.current_stage || task.currentStage),
        timestamp: new Date().toISOString(),
        source,
        message: String(payload.message || payload.metadata?.message || ""),
      };
      const previousEvent = task.events[task.events.length - 1];
      if (
        previousEvent &&
        previousEvent.event === eventEntry.event &&
        previousEvent.status === eventEntry.status &&
        previousEvent.progress === eventEntry.progress &&
        previousEvent.currentStage === eventEntry.currentStage &&
        previousEvent.message === eventEntry.message
      ) {
        return previous;
      }
      return {
        ...previous,
        [taskId]: normalizeTaskRecord({
          ...task,
          events: [...task.events, eventEntry].slice(-30),
        }),
      };
    });
  }, [updateTasks]);

  const applyTaskSnapshot = useCallback(async (taskId: string, payload: TaskSnapshotPayload, source: string) => {
    const previous = tasksRef.current[taskId];
    const status = String(payload.status || previous?.status || "submitted") as TaskStatus;
    const task = upsertTask(taskId, {
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

    appendTaskEvent(taskId, payload as Record<string, unknown>, source);
    await hydrateArtifact(task);
    const hydratedTask = tasksRef.current[taskId] || task;

    if (hydratedTask.status === "succeeded" && !hydratedTask.resolvedArtifactUrl && !hydratedTask.successRefreshScheduled) {
      upsertTask(taskId, {
        successRefreshScheduled: true,
        note: hydratedTask.note || "模型已完成，正在补拉 artifact 详情…",
      });
      fetchTask(configRef.current, taskId)
        .then((response) => applyTaskSnapshot(taskId, response, "snapshot"))
        .catch((error) => {
          console.warn("post-success refresh failed", error);
        })
        .finally(() => {
          if (tasksRef.current[taskId]) {
            upsertTask(taskId, { successRefreshScheduled: false });
          }
        });
    }

    if (TERMINAL_STATUSES.has(hydratedTask.status)) {
      stopSubscription(taskId);
    }
    if (generateRef.current.currentTaskId === taskId || (isActiveStatus(hydratedTask.status) && !generateRef.current.currentTaskId)) {
      setCurrentTaskId(taskId);
    }
  }, [appendTaskEvent, hydrateArtifact, setCurrentTaskId, stopSubscription, upsertTask]);

  const applyEventPayload = useCallback(async (taskId: string, payload: Record<string, any>, source: string) => {
    const metadata = payload.metadata || {};
    await applyTaskSnapshot(taskId, {
      status: payload.status,
      progress: payload.progress,
      currentStage: payload.currentStage,
      updatedAt: new Date().toISOString(),
      error: metadata.error || metadata.failed_stage || metadata.message
        ? {
            message: metadata.message || metadata.error || "",
            failed_stage: metadata.failed_stage || metadata.stage || null,
          }
        : tasksRef.current[taskId]?.error || null,
      artifacts: metadata.artifacts || tasksRef.current[taskId]?.artifacts || [],
    }, source);
  }, [applyTaskSnapshot]);

  const replaceTasksFromServer = useCallback(async (taskSummaries: TaskSummaryPayload[], append = false) => {
    const nextTasks = append ? { ...tasksRef.current } : {};
    taskSummaries.forEach((summary) => {
      const taskId = String(summary.taskId || summary.task_id || "").trim();
      if (!taskId) {
        return;
      }
      const current = tasksRef.current[taskId];
      nextTasks[taskId] = normalizeTaskRecord({
        ...(current || {}),
        taskId,
        model: summary.model || current?.model || "trellis",
        inputUrl: summary.inputUrl || summary.input_url || current?.inputUrl || "",
        createdAt: summary.createdAt || summary.created_at || current?.createdAt,
        updatedAt: summary.finishedAt || summary.finished_at || current?.updatedAt || current?.lastSeenAt,
        lastSeenAt: new Date().toISOString(),
        status: String(summary.status || current?.status || "submitted") as TaskStatus,
        statusLabel: formatTaskStatus(String(summary.status || current?.status || "submitted")),
        currentStage: current?.currentStage || String(summary.status || current?.status || "submitted"),
        progress: current?.progress ?? defaultProgressForStatus(String(summary.status || "submitted")),
        artifacts: summary.artifactUrl || summary.artifact_url
          ? [{ type: "glb", url: summary.artifactUrl || summary.artifact_url }]
          : current?.artifacts || [],
        rawArtifactUrl: summary.artifactUrl || summary.artifact_url || current?.rawArtifactUrl || "",
        transport: TERMINAL_STATUSES.has((summary.status || "") as TaskStatus)
          ? "complete"
          : current?.transport || "idle",
        resolvedArtifactUrl: current?.resolvedArtifactUrl || "",
        previewDataUrl: current?.previewDataUrl || "",
        note: current?.note || "",
      });
    });

    if (!append) {
      Array.from(subscriptionsRef.current.keys()).forEach((taskId) => {
        if (!nextTasks[taskId]) {
          stopSubscription(taskId);
        }
      });
    }

    updateTasks(() => nextTasks);
    await Promise.all(Object.values(nextTasks).map((task) => hydrateArtifact(task)));
    syncCurrentTaskSelection(nextTasks);
  }, [hydrateArtifact, stopSubscription, syncCurrentTaskSelection, updateTasks]);

  const refreshTaskListAction = useCallback(async ({ append = false, resubscribe = false, silent = false } = {}) => {
    if (!configRef.current.baseUrl) {
      throw new Error("请先填写 API Base URL");
    }
    if (!configRef.current.token) {
      setConnection((previous) => ({
        ...previous,
        tone: "empty",
        label: "未配置 API Key",
        detail: "打开设置页以保存连接信息",
      }));
      resetTaskState();
      return;
    }

    updateTaskPage((previous) => ({ ...previous, isLoading: true }));
    const payload = await fetchTaskList(configRef.current, append ? taskPageRef.current.nextCursor : "", taskPageRef.current.limit) as TaskListPayload;
    await replaceTasksFromServer(Array.isArray(payload.items) ? payload.items : [], append);
    updateTaskPage((previous) => ({
      ...previous,
      isLoading: false,
      nextCursor: String(payload.nextCursor || payload.next_cursor || ""),
      hasMore: Boolean(payload.hasMore ?? payload.has_more),
    }));
    if (resubscribe) {
      const sorted = Object.values(tasksRef.current).sort(compareTaskRecords);
      for (const task of sorted) {
        if (isActiveStatus(task.status)) {
          await subscribeToTask(task.taskId, true);
        }
      }
    }
    if (!silent) {
      toast.success(append ? "更多任务已加载" : "图库已刷新", {
        description: `当前共有 ${Object.keys(tasksRef.current).length} 条任务记录。`,
      });
    }
  }, [replaceTasksFromServer, resetTaskState, updateTaskPage]);

  const refreshTaskAction = useCallback(async (taskId: string, { silent = true } = {}) => {
    const payload = await fetchTask(configRef.current, taskId);
    await applyTaskSnapshot(taskId, payload, "snapshot");
    if (!silent) {
      toast.success("任务已刷新", {
        description: `任务 ${taskId.slice(-8)} 的详情已更新。`,
      });
    }
  }, [applyTaskSnapshot]);

  const parseSseEvent = useCallback((rawBlock: string) => {
    if (!rawBlock.trim()) {
      return null;
    }
    let eventName = "";
    const dataLines: string[] = [];
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
  }, []);

  const startPolling = useCallback((taskId: string) => {
    stopSubscription(taskId);
    const timer = window.setInterval(() => {
      refreshTaskAction(taskId, { silent: true }).catch((error) => {
        console.warn("polling refresh failed", error);
        upsertTask(taskId, {
          transport: "polling",
          note: `轮询失败：${error instanceof Error ? error.message : String(error)}`,
        });
      });
    }, POLL_INTERVAL_MS);
    subscriptionsRef.current.set(taskId, { mode: "polling", timer });
  }, [refreshTaskAction, stopSubscription, upsertTask]);

  const connectSse = useCallback(async (taskId: string) => {
    const controller = new AbortController();
    subscriptionsRef.current.set(taskId, {
      mode: "sse",
      controller,
    });
    upsertTask(taskId, {
      transport: "sse",
      note: "SSE 已连接。",
    });

    const response = await fetch(buildApiUrl(configRef.current.baseUrl, `/v1/tasks/${encodeURIComponent(taskId)}/events`), {
      headers: authHeaders(configRef.current.token, false),
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
    let firstEventWatchdog: number | null = window.setTimeout(() => {
      const task = tasksRef.current[taskId];
      if (controller.signal.aborted || (task && TERMINAL_STATUSES.has(task.status))) {
        return;
      }
      upsertTask(taskId, {
        transport: "polling",
        note: "SSE 已连接但长时间未收到事件，已降级为轮询。",
      });
      startPolling(taskId);
    }, 2500);

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
          if (firstEventWatchdog != null) {
            window.clearTimeout(firstEventWatchdog);
            firstEventWatchdog = null;
          }
          await applyEventPayload(taskId, payload, "sse");
          if (TERMINAL_STATUSES.has(payload.status as TaskStatus)) {
            reachedTerminal = true;
          }
        }
      }

      const tail = parseSseEvent(buffer.replace(/\r/g, ""));
      if (tail) {
        if (firstEventWatchdog != null) {
          window.clearTimeout(firstEventWatchdog);
          firstEventWatchdog = null;
        }
        await applyEventPayload(taskId, tail, "sse");
        if (TERMINAL_STATUSES.has(tail.status as TaskStatus)) {
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
      } catch {
        // ignore release errors
      }
      if (firstEventWatchdog != null) {
        window.clearTimeout(firstEventWatchdog);
      }
    }

    const currentTask = tasksRef.current[taskId];
    if (reachedTerminal || (currentTask && TERMINAL_STATUSES.has(currentTask.status))) {
      await fetchTask(configRef.current, taskId)
        .then((payload) => applyTaskSnapshot(taskId, payload, "snapshot"))
        .catch((error) => {
          console.warn("terminal refresh failed", error);
        });
      upsertTask(taskId, {
        transport: "complete",
        note: tasksRef.current[taskId]?.note || "任务已进入终态。",
      });
      stopSubscription(taskId);
      return;
    }
    throw new Error("SSE 已断开，任务尚未结束");
  }, [applyEventPayload, parseSseEvent, startPolling, stopSubscription, upsertTask]);

  const subscribeToTask = useCallback(async (taskId: string, force = false) => {
    if (!configRef.current.baseUrl) {
      throw new Error("请先填写 API Base URL");
    }
    if (!configRef.current.token) {
      throw new Error("请先配置 API Key");
    }
    if (!force && subscriptionsRef.current.has(taskId)) {
      return;
    }
    stopSubscription(taskId);
    upsertTask(taskId, {
      transport: "connecting",
      note: "正在连接实时进度流…",
    });

    try {
      await refreshTaskAction(taskId, { silent: true });
    } catch (error) {
      console.warn("initial task refresh failed before SSE", error);
    }

    try {
      await connectSse(taskId);
    } catch (error) {
      console.warn("falling back to polling", error);
      upsertTask(taskId, {
        transport: "polling",
        note: "SSE 连接失败，已降级为每 3 秒轮询。",
      });
      startPolling(taskId);
    }
  }, [connectSse, refreshTaskAction, startPolling, stopSubscription, upsertTask]);

  const pingHealthAction = useCallback(async (silent = false) => {
    try {
      const payload = await fetchHealth(configRef.current);
      setConnection({
        tone: "ready",
        label: "服务在线",
        detail: `进程存活 · ${payload.service}`,
      });
      if (!silent) {
        toast.success("服务在线", {
          description: `已连接到 ${payload.service}。`,
        });
      }
      return payload;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setConnection({
        tone: "error",
        label: "服务离线",
        detail: message,
      });
      if (!silent) {
        toast.error("服务检查失败", {
          description: message,
        });
      }
      throw error;
    }
  }, []);

  const clearSelectedFile = useCallback((keepStatus = false) => {
    setGenerate((previous) => ({
      ...previous,
      file: null,
      previewDataUrl: "",
      uploadedUrl: "",
      uploadId: "",
      name: "",
      uploadProgress: 0,
      statusMessage: keepStatus
        ? previous.statusMessage
        : configRef.current.token
          ? "图片就绪后会自动上传，然后直接开始生成。"
          : "请先到设置页配置连接。",
      statusTone: keepStatus ? previous.statusTone : configRef.current.token ? "info" : "error",
    }));
  }, []);

  const selectFile = useCallback(async (file: File | null) => {
    if (!file) {
      clearSelectedFile(false);
      return;
    }
    const previewDataUrl = await readFileAsDataUrl(file);
    setGenerate((previous) => ({
      ...previous,
      file,
      previewDataUrl,
      uploadedUrl: "",
      uploadId: "",
      name: file.name,
      statusMessage: configRef.current.token
        ? "图片已准备；提交后会自动上传并创建任务。"
        : "图片预览已就绪；请先配置 API Key。",
      statusTone: configRef.current.token ? "info" : "error",
    }));
  }, [clearSelectedFile]);

  const ensureUploadedInput = useCallback(async () => {
    if (!configRef.current.baseUrl) {
      throw new Error("请先填写 API Base URL");
    }
    if (!configRef.current.token) {
      throw new Error("请先配置 API Key");
    }
    if (!generateRef.current.file) {
      throw new Error("请先选择一张输入图片");
    }
    if (generateRef.current.uploadedUrl) {
      return generateRef.current.uploadedUrl;
    }
    setGenerate((previous) => ({
      ...previous,
      isUploading: true,
      uploadProgress: 0,
      statusMessage: "正在上传图片：0%",
      statusTone: "info",
    }));
    try {
      const result = await uploadFile(configRef.current, generateRef.current.file, (progress) => {
        setGenerate((previous) => ({
          ...previous,
          uploadProgress: progress,
          statusMessage: `正在上传图片：${progress}%`,
          statusTone: "info",
        }));
      });
      setGenerate((previous) => ({
        ...previous,
        uploadedUrl: result.url,
        uploadId: String(result.uploadId || result.upload_id || ""),
        statusMessage: "上传完成，正在创建任务…",
        statusTone: "success",
      }));
      return result.url;
    } finally {
      setGenerate((previous) => ({
        ...previous,
        isUploading: false,
      }));
    }
  }, []);

  const submitNewTask = useCallback(async (inputUrl: string, previewDataUrl?: string) => {
    const callbackUrl = String(generateRef.current.callbackUrl || "").trim();
    const payload: TaskCreatePayload = {
      type: "image_to_3d",
      image_url: inputUrl,
    };
    if (callbackUrl) {
      payload.callback_url = callbackUrl;
    }

    setGenerate((previous) => ({
      ...previous,
      isSubmitting: true,
      statusMessage: "正在创建任务…",
      statusTone: "info",
    }));

    try {
      const result = await createTask(configRef.current, payload);
      const taskId = String(result.taskId || result.task_id || "");
      setCurrentTaskId(taskId);
      upsertTask(taskId, {
        status: String(result.status || "submitted"),
        statusLabel: formatTaskStatus(String(result.status || "submitted")),
        currentStage: String(result.status || "submitted"),
        progress: defaultProgressForStatus(String(result.status || "submitted")),
        queuePosition: result.queuePosition ?? result.queue_position ?? null,
        estimatedWaitSeconds: result.estimatedWaitSeconds ?? result.estimated_wait_seconds ?? null,
        estimatedFinishAt: result.estimatedFinishAt || result.estimated_finish_at || null,
        model: result.model || "trellis",
        inputUrl: result.inputUrl || result.input_url || inputUrl,
        createdAt: new Date().toISOString(),
        submittedAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        lastSeenAt: new Date().toISOString(),
        transport: "connecting",
        note: "任务已提交，正在连接实时进度流。",
        previewDataUrl: previewDataUrl || generateRef.current.previewDataUrl,
        artifacts: [],
        events: [],
      });
      await refreshTaskListAction({ append: false, resubscribe: false, silent: true }).catch((error) => {
        console.warn("silent list refresh failed after submit", error);
      });
      subscribeToTask(taskId, true).catch((error) => {
        console.warn("background subscription failed after submit", error);
        toast.error("实时连接失败", {
          description: error instanceof Error ? error.message : String(error),
        });
      });
      toast.success("任务已创建", {
        description: `任务 ${taskId.slice(-8)} 已提交，正在建立实时连接。`,
      });
      return taskId;
    } finally {
      setGenerate((previous) => ({
        ...previous,
        isSubmitting: false,
      }));
    }
  }, [refreshTaskListAction, setCurrentTaskId, subscribeToTask, upsertTask]);

  const submitCurrentFile = useCallback(async () => {
    if (generateRef.current.isUploading || generateRef.current.isSubmitting) {
      return undefined;
    }
    const inputUrl = await ensureUploadedInput();
    return submitNewTask(inputUrl, generateRef.current.previewDataUrl);
  }, [ensureUploadedInput, submitNewTask]);

  const retryCurrentTask = useCallback(async () => {
    const currentTask = tasksRef.current[generateRef.current.currentTaskId];
    if (!currentTask?.inputUrl) {
      throw new Error("当前任务缺少 input_url，无法重试。请重新上传图片。");
    }
    return submitNewTask(currentTask.inputUrl, currentTask.previewDataUrl || generateRef.current.previewDataUrl);
  }, [submitNewTask]);

  const cancelTask = useCallback(async (taskId: string) => {
    upsertTask(taskId, { pendingCancel: true });
    try {
      const payload = await requestTaskCancel(configRef.current, taskId);
      await applyTaskSnapshot(taskId, payload, "snapshot");
      toast.success("任务已取消", {
        description: `任务 ${taskId.slice(-8)} 已进入 cancelled 状态。`,
      });
    } finally {
      if (tasksRef.current[taskId]) {
        upsertTask(taskId, { pendingCancel: false });
      }
    }
  }, [applyTaskSnapshot, upsertTask]);

  const deleteTask = useCallback(async (taskId: string) => {
    upsertTask(taskId, { pendingDelete: true });
    try {
      await requestTaskDelete(configRef.current, taskId);
      removeTask(taskId);
      toast.success("任务已删除", {
        description: `任务 ${taskId.slice(-8)} 已从列表中移除。`,
      });
    } finally {
      if (tasksRef.current[taskId]) {
        upsertTask(taskId, { pendingDelete: false });
      }
    }
  }, [removeTask, upsertTask]);

  const saveConfig = useCallback(async (next: Partial<ApiConfig>) => {
    persistConfig(next);
    const merged = {
      baseUrl: normalizeBaseUrl(next.baseUrl ?? configRef.current.baseUrl),
      token: String(next.token ?? configRef.current.token).trim(),
    };
    configRef.current = merged;
    const results = await Promise.allSettled([
      pingHealthAction(true),
      merged.token ? refreshTaskListAction({ append: false, resubscribe: true, silent: true }) : Promise.resolve(),
    ]);
    const refreshResult = results[1];
    if (refreshResult?.status === "rejected") {
      toast.success("配置已保存", {
        description: `API Key 与 Base URL 已更新，但任务列表刷新失败：${refreshResult.reason instanceof Error ? refreshResult.reason.message : String(refreshResult.reason)}`,
      });
      return;
    }
    toast.success("配置已保存", {
      description: "API Key 与 Base URL 已更新。",
    });
  }, [persistConfig, pingHealthAction, refreshTaskListAction]);

  useEffect(() => {
    if (config.baseUrl) {
      pingHealthAction(true).catch(() => undefined);
    }
    if (config.baseUrl && config.token) {
      refreshTaskListAction({ append: false, resubscribe: true, silent: true }).catch((error) => {
        toast.error("加载任务失败", {
          description: error instanceof Error ? error.message : String(error),
        });
      });
    }

    return () => {
      Array.from(subscriptionsRef.current.keys()).forEach((taskId) => stopSubscription(taskId));
    };
  }, []);

  const sortedTasks = useMemo(() => Object.values(tasks).sort(compareTaskRecords), [tasks]);
  const currentTask = useMemo(() => (generate.currentTaskId ? tasks[generate.currentTaskId] || null : null), [generate.currentTaskId, tasks]);
  const generateView = useMemo<GenerateView>(() => {
    if (generate.isUploading || generate.isSubmitting) {
      return "uploading";
    }
    if (!currentTask) {
      return "idle";
    }
    if (currentTask.status === "succeeded") {
      return "completed";
    }
    if (currentTask.status === "failed" || currentTask.status === "cancelled") {
      return "failed";
    }
    return "processing";
  }, [currentTask, generate.isSubmitting, generate.isUploading]);

  const getFilteredTasks = useCallback((filter: GalleryFilter = galleryFilter) => {
    if (filter === "processing") {
      return sortedTasks.filter((task) => isActiveStatus(task.status));
    }
    if (filter === "completed") {
      return sortedTasks.filter((task) => task.status === "succeeded");
    }
    if (filter === "failed") {
      return sortedTasks.filter((task) => task.status === "failed" || task.status === "cancelled");
    }
    return sortedTasks;
  }, [galleryFilter, sortedTasks]);

  const value = useMemo<Gen3dContextValue>(() => ({
    config,
    connection,
    tasks: sortedTasks,
    taskMap: tasks,
    taskPage,
    generate,
    currentTask,
    generateView,
    galleryFilter,
    setGalleryFilter,
    getFilteredTasks,
    saveConfig,
    pingHealth: pingHealthAction,
    refreshTaskList: refreshTaskListAction,
    refreshTask: refreshTaskAction,
    selectFile,
    clearSelectedFile,
    submitCurrentFile,
    retryCurrentTask,
    cancelTask,
    deleteTask,
    subscribeToTask,
    setCurrentTaskId,
  }), [
    cancelTask,
    clearSelectedFile,
    config,
    connection,
    currentTask,
    galleryFilter,
    generate,
    generateView,
    getFilteredTasks,
    pingHealthAction,
    refreshTaskAction,
    refreshTaskListAction,
    retryCurrentTask,
    saveConfig,
    selectFile,
    sortedTasks,
    subscribeToTask,
    submitCurrentFile,
    taskPage,
    tasks,
    deleteTask,
    setCurrentTaskId,
  ]);

  return <Gen3dContext.Provider value={value}>{children}</Gen3dContext.Provider>;
}

export function useGen3d() {
  const context = useContext(Gen3dContext);
  if (!context) {
    throw new Error("useGen3d must be used within Gen3dProvider");
  }
  return context;
}

export function canCancelTask(task: TaskRecord | null | undefined) {
  return Boolean(task) && CANCELLABLE_STATUSES.has((task?.status || "") as TaskStatus) && !task?.pendingCancel;
}
