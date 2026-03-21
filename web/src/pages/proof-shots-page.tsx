import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Gen3dContext, type Gen3dContextValue } from "@/app/gen3d-provider";
import { AppShell } from "@/components/app-shell";
import { GalleryPage } from "@/pages/gallery-page";
import { GeneratePage } from "@/pages/generate-page";
import { renderModelThumbnail } from "@/lib/viewer";
import type {
  ApiConfig,
  ConnectionState,
  GalleryFilter,
  GenerateState,
  GenerateView,
  TaskPageState,
  TaskRecord,
} from "@/lib/types";

const MODEL_URL = "/fixtures/compare-model.glb";
const INPUT_URL = "/fixtures/compare-input.png";

type ProofMode =
  | "generate-empty"
  | "generate-processing"
  | "generate-completed"
  | "gallery-grid"
  | "gallery-modal";

const baseConfig: ApiConfig = {
  baseUrl: "",
  token: "",
};

const baseConnection: ConnectionState = {
  tone: "ready",
  label: "已连接",
  detail: "服务正常",
};

const baseTaskPage: TaskPageState = {
  limit: 20,
  nextCursor: "",
  hasMore: false,
  isLoading: false,
};

const baseGenerateState: GenerateState = {
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
  currentTaskId: "",
};

function buildTask({
  taskId,
  status,
  createdAt,
  progress = status === "succeeded" ? 100 : 48,
  thumbnailUrl = "",
  thumbnailState = "idle",
}: {
  taskId: string;
  status: TaskRecord["status"];
  createdAt: string;
  progress?: number;
  thumbnailUrl?: string;
  thumbnailState?: TaskRecord["thumbnailState"];
}): TaskRecord {
  return {
    taskId,
    model: "image_to_3d",
    inputUrl: INPUT_URL,
    createdAt,
    submittedAt: createdAt,
    updatedAt: createdAt,
    lastSeenAt: createdAt,
    status,
    statusLabel: status,
    progress,
    currentStage: status,
    queuePosition: null,
    estimatedWaitSeconds: null,
    estimatedFinishAt: null,
    artifacts: status === "succeeded" ? [{ type: "glb", url: MODEL_URL }] : [],
    error: status === "failed" ? { message: "本次生成未完成" } : null,
    events: [],
    transport: "idle",
    note: status === "failed" ? "本次生成未完成" : "",
    resolvedArtifactUrl: status === "succeeded" ? MODEL_URL : "",
    rawArtifactUrl: status === "succeeded" ? MODEL_URL : "",
    previewDataUrl: INPUT_URL,
    thumbnailUrl,
    thumbnailState,
    pendingDelete: false,
    pendingCancel: false,
    successRefreshScheduled: false,
  };
}

function Provider({
  value,
  children,
}: {
  value: Gen3dContextValue;
  children: ReactNode;
}) {
  return <Gen3dContext.Provider value={value}>{children}</Gen3dContext.Provider>;
}

function getMode(): ProofMode {
  const value = new URLSearchParams(window.location.search).get("mode");
  switch (value) {
    case "generate-processing":
    case "generate-completed":
    case "gallery-grid":
    case "gallery-modal":
      return value;
    default:
      return "generate-empty";
  }
}

export function ProofShotsPage() {
  const mode = useMemo(() => getMode(), []);
  const activePath = mode.startsWith("gallery") ? "/gallery" : "/";
  const needsThumbnail = true;
  const [thumbnailUrl, setThumbnailUrl] = useState("");

  useEffect(() => {
    if (!needsThumbnail) {
      const timeout = window.setTimeout(() => {
        (window as Window & { __shotReady?: boolean }).__shotReady = true;
      }, mode === "generate-completed" ? 900 : 250);
      return () => window.clearTimeout(timeout);
    }

    let active = true;
    renderModelThumbnail(MODEL_URL, {
      width: 400,
      height: 400,
      background: "#2a2a2a",
    })
      .then((url) => {
        if (active) {
          setThumbnailUrl(url);
          (window as Window & { __shotReady?: boolean }).__shotReady = true;
        }
      })
      .catch(() => {
        if (active) {
          setThumbnailUrl("");
          (window as Window & { __shotReady?: boolean }).__shotReady = true;
        }
      });

    return () => {
      active = false;
    };
  }, [needsThumbnail]);

  const completedTask = useMemo(
    () => buildTask({
      taskId: "shot-completed",
      status: "succeeded",
      createdAt: new Date(Date.now() - 65 * 60 * 1000).toISOString(),
      progress: 100,
      thumbnailUrl,
      thumbnailState: thumbnailUrl ? "ready" : "loading",
    }),
    [thumbnailUrl],
  );

  const processingTask = useMemo(
    () => buildTask({
      taskId: "shot-processing",
      status: "queued",
      createdAt: new Date(Date.now() - 14 * 60 * 1000).toISOString(),
      progress: 64,
    }),
    [],
  );

  const failedTask = useMemo(
    () => buildTask({
      taskId: "shot-failed",
      status: "failed",
      createdAt: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
      progress: 100,
    }),
    [],
  );

  const galleryTasks = useMemo(
    () => [
      completedTask,
      buildTask({
        taskId: "shot-completed-2",
        status: "succeeded",
        createdAt: new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString(),
        progress: 100,
        thumbnailUrl,
        thumbnailState: thumbnailUrl ? "ready" : "loading",
      }),
      processingTask,
      failedTask,
    ],
    [completedTask, failedTask, processingTask, thumbnailUrl],
  );
  const generateTasks = useMemo(() => {
    if (mode === "generate-processing") {
      return [processingTask, completedTask, failedTask];
    }
    if (mode === "generate-completed") {
      return [completedTask, processingTask, failedTask];
    }
    return [completedTask, processingTask, failedTask];
  }, [completedTask, failedTask, mode, processingTask]);

  const noopAsync = async () => undefined;
  const noopVoid = async () => {};

  const generateContext = useMemo<Gen3dContextValue>(() => {
    let generate: GenerateState = { ...baseGenerateState };
    let currentTask: TaskRecord | null = null;
    let generateView: GenerateView = "idle";
    let tasks: TaskRecord[] = generateTasks;

    if (mode === "generate-processing") {
      generate = {
        ...baseGenerateState,
        previewDataUrl: INPUT_URL,
        uploadedUrl: INPUT_URL,
        name: "compare-input.png",
        currentTaskId: processingTask.taskId,
      };
      currentTask = processingTask;
      generateView = "processing";
    }

    if (mode === "generate-completed") {
      generate = {
        ...baseGenerateState,
        previewDataUrl: INPUT_URL,
        uploadedUrl: INPUT_URL,
        name: "compare-input.png",
        currentTaskId: completedTask.taskId,
      };
      currentTask = completedTask;
      generateView = "completed";
    }

    if (mode === "generate-empty") {
      generate = {
        ...baseGenerateState,
      };
    }

    const taskMap = Object.fromEntries(tasks.map((task) => [task.taskId, task]));

    return {
      config: baseConfig,
      connection: baseConnection,
      tasks,
      taskMap,
      taskPage: baseTaskPage,
      generate,
      currentTask,
      generateView,
      galleryFilter: "all",
      setGalleryFilter: (_filter: GalleryFilter) => undefined,
      getFilteredTasks: () => tasks,
      saveConfig: async () => {},
      pingHealth: async () => ({ status: "ready", service: "cubie3d" }),
      refreshTaskList: async () => {},
      refreshTask: async () => {},
      selectFile: async () => {},
      clearSelectedFile: () => undefined,
      submitCurrentFile: noopAsync,
      retryCurrentTask: noopAsync,
      cancelTask: noopVoid,
      deleteTask: noopVoid,
      subscribeToTask: noopVoid,
      setCurrentTaskId: () => undefined,
      clearCurrentTaskSelection: () => undefined,
    };
  }, [completedTask, generateTasks, mode, processingTask]);

  const galleryContext = useMemo<Gen3dContextValue>(() => ({
    config: baseConfig,
    connection: baseConnection,
    tasks: galleryTasks,
    taskMap: Object.fromEntries(galleryTasks.map((task) => [task.taskId, task])),
    taskPage: baseTaskPage,
    generate: baseGenerateState,
    currentTask: null,
    generateView: "idle",
    galleryFilter: "all",
    setGalleryFilter: (_filter: GalleryFilter) => undefined,
    getFilteredTasks: (filter = "all") => {
      if (filter === "all") {
        return galleryTasks;
      }
      if (filter === "processing") {
        return galleryTasks.filter((task) => task.status !== "succeeded" && task.status !== "failed" && task.status !== "cancelled");
      }
      if (filter === "completed") {
        return galleryTasks.filter((task) => task.status === "succeeded");
      }
      return galleryTasks.filter((task) => task.status === "failed" || task.status === "cancelled");
    },
    saveConfig: async () => {},
    pingHealth: async () => ({ status: "ready", service: "cubie3d" }),
    refreshTaskList: async () => {},
    refreshTask: async () => {},
    selectFile: async () => {},
    clearSelectedFile: () => undefined,
    submitCurrentFile: noopAsync,
    retryCurrentTask: noopAsync,
    cancelTask: noopVoid,
    deleteTask: noopVoid,
    subscribeToTask: noopVoid,
    setCurrentTaskId: () => undefined,
    clearCurrentTaskSelection: () => undefined,
  }), [galleryTasks]);

  return (
    <Provider value={mode.startsWith("generate") ? generateContext : galleryContext}>
      <AppShell activePath={activePath}>
        {mode.startsWith("generate") ? (
          <GeneratePage />
        ) : (
          <GalleryPage initialSelectedTaskId={mode === "gallery-modal" ? completedTask.taskId : ""} />
        )}
      </AppShell>
    </Provider>
  );
}
