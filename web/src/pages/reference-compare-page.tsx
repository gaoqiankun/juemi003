import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Gen3dContext, type Gen3dContextValue } from "@/app/gen3d-provider";
import { AppShell } from "@/components/app-shell";
import { GalleryPage } from "@/pages/gallery-page";
import { GeneratePage } from "@/pages/generate-page";
import { renderModelThumbnail } from "@/lib/viewer";
import type {
  ApiConfig,
  ConnectionState,
  GenerateState,
  TaskPageState,
  TaskRecord,
} from "@/lib/types";

const MODEL_URL = "/fixtures/compare-model.glb";
const INPUT_URL = "/fixtures/compare-input.png";
const REFERENCE_GALLERY_URL = "/fixtures/reference-assets-grid.png";
const REFERENCE_COMPLETED_URL = "/fixtures/reference-model-viewer-completed.png";
const COMPARE_BASE_TS = Date.now();
const COMPARE_GALLERY_CREATED_AT = new Date(COMPARE_BASE_TS - 2 * 60 * 60 * 1000).toISOString();
const COMPARE_COMPLETED_CREATED_AT = new Date(COMPARE_BASE_TS - 35 * 60 * 1000).toISOString();

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

const baseGenerate: GenerateState = {
  file: null,
  previewDataUrl: INPUT_URL,
  uploadedUrl: INPUT_URL,
  uploadId: "",
  name: "compare-input.png",
  callbackUrl: "",
  isUploading: false,
  uploadProgress: 100,
  isSubmitting: false,
  statusMessage: "",
  statusTone: "info",
  currentTaskId: "",
};

type CompareMode = "all" | "gallery" | "completed";

function buildTask({
  taskId,
  status,
  createdAt,
  thumbnailUrl = "",
  thumbnailState = "idle",
}: {
  taskId: string;
  status: TaskRecord["status"];
  createdAt: string;
  thumbnailUrl?: string;
  thumbnailState?: TaskRecord["thumbnailState"];
}): TaskRecord {
  return {
    taskId,
    model: "trellis",
    inputUrl: INPUT_URL,
    createdAt,
    submittedAt: createdAt,
    updatedAt: createdAt,
    lastSeenAt: createdAt,
    status,
    statusLabel: status,
    progress: status === "succeeded" ? 100 : 56,
    currentStage: status,
    queuePosition: null,
    estimatedWaitSeconds: null,
    estimatedFinishAt: null,
    artifacts: status === "succeeded" ? [{ type: "glb", url: MODEL_URL }] : [],
    error: null,
    events: [],
    transport: status === "succeeded" ? "complete" : "idle",
    note: "",
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

function CompareContextProvider({
  value,
  children,
}: {
  value: Gen3dContextValue;
  children: ReactNode;
}) {
  return <Gen3dContext.Provider value={value}>{children}</Gen3dContext.Provider>;
}

function ComparisonPanel({
  title,
  live,
  referenceSrc,
}: {
  title: string;
  live: ReactNode;
  referenceSrc: string;
}) {
  return (
    <section className="space-y-4">
      <div className="text-lg font-semibold tracking-[-0.02em] text-white">{title}</div>
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="overflow-hidden rounded-[18px] border border-white/10 bg-[#050505]">
          <div className="border-b border-white/10 bg-[#0d0d0d] px-4 py-3 text-sm text-white/66">当前实现</div>
          <div className="overflow-hidden">{live}</div>
        </div>
        <div className="overflow-hidden rounded-[18px] border border-white/10 bg-[#050505]">
          <div className="border-b border-white/10 bg-[#0d0d0d] px-4 py-3 text-sm text-white/66">参考图</div>
          <div className="bg-black p-3">
            <img src={referenceSrc} alt={title} className="w-full rounded-[12px] object-contain" />
          </div>
        </div>
      </div>
    </section>
  );
}

export function ReferenceComparePage() {
  const compareMode = useMemo<CompareMode>(() => {
    const value = new URLSearchParams(window.location.search).get("mode");
    if (value === "gallery" || value === "completed") {
      return value;
    }
    return "all";
  }, []);
  const shouldRenderGallery = compareMode !== "completed";
  const shouldRenderCompleted = compareMode !== "gallery";
  const [thumbnailUrl, setThumbnailUrl] = useState("");

  useEffect(() => {
    if (!shouldRenderGallery) {
      return undefined;
    }
    let active = true;
    renderModelThumbnail(MODEL_URL, {
      width: 560,
      height: 560,
      background: "#242424",
    })
      .then((url) => {
        if (active) {
          setThumbnailUrl(url);
        }
      })
      .catch(() => {
        if (active) {
          setThumbnailUrl("");
        }
      });
    return () => {
      active = false;
    };
  }, [shouldRenderGallery]);

  useEffect(() => {
    (window as Window & { __compareReady?: boolean }).__compareReady = shouldRenderGallery ? Boolean(thumbnailUrl) : true;
  }, [shouldRenderGallery, thumbnailUrl]);

  const galleryTask = useMemo(
    () => buildTask({
      taskId: "compare-gallery-task",
      status: "succeeded",
      createdAt: COMPARE_GALLERY_CREATED_AT,
      thumbnailUrl,
      thumbnailState: thumbnailUrl ? "ready" : "loading",
    }),
    [thumbnailUrl],
  );

  const completedTask = useMemo(
    () => buildTask({
      taskId: "compare-completed-task",
      status: "succeeded",
      createdAt: COMPARE_COMPLETED_CREATED_AT,
      thumbnailUrl,
      thumbnailState: thumbnailUrl ? "ready" : "loading",
    }),
    [thumbnailUrl],
  );

  const noopAsync = async () => undefined;
  const noopVoid = async () => {};

  const galleryValue = useMemo<Gen3dContextValue>(() => ({
    config: baseConfig,
    connection: baseConnection,
    tasks: [galleryTask],
    taskMap: { [galleryTask.taskId]: galleryTask },
    taskPage: baseTaskPage,
    generate: baseGenerate,
    currentTask: null,
    generateView: "idle",
    galleryFilter: "all",
    setGalleryFilter: () => undefined,
    getFilteredTasks: () => [galleryTask],
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
  }), [galleryTask]);

  const completedValue = useMemo<Gen3dContextValue>(() => ({
    config: baseConfig,
    connection: baseConnection,
    tasks: [completedTask],
    taskMap: { [completedTask.taskId]: completedTask },
    taskPage: baseTaskPage,
    generate: {
      ...baseGenerate,
      currentTaskId: completedTask.taskId,
    },
    currentTask: completedTask,
    generateView: "completed",
    galleryFilter: "all",
    setGalleryFilter: () => undefined,
    getFilteredTasks: () => [completedTask],
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
  }), [completedTask]);

  return (
    <main className="min-h-screen bg-[#050505] px-6 py-8 text-white">
      <div className="mx-auto max-w-[1680px] space-y-10">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-[-0.03em] text-white">Web UI 对比截图</h1>
          <p className="text-sm text-white/56">左侧为当前实现，右侧为用户指定参考图。</p>
        </header>

        {shouldRenderGallery ? (
          <ComparisonPanel
            title="图库页"
            live={(
              <CompareContextProvider value={galleryValue}>
                <AppShell activePath="/gallery" embedded>
                  <GalleryPage />
                </AppShell>
              </CompareContextProvider>
            )}
            referenceSrc={REFERENCE_GALLERY_URL}
          />
        ) : null}

        {shouldRenderCompleted ? (
          <ComparisonPanel
            title="Completed 页"
            live={(
              <CompareContextProvider value={completedValue}>
                <AppShell activePath="/" embedded>
                  <GeneratePage />
                </AppShell>
              </CompareContextProvider>
            )}
            referenceSrc={REFERENCE_COMPLETED_URL}
          />
        ) : null}
      </div>
    </main>
  );
}
