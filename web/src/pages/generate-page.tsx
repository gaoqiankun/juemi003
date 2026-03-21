import { ArrowRight, Download, Eye, History, RotateCcw, Sparkles, UploadCloud, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { useGen3d } from "@/app/gen3d-provider";
import { ModelViewport } from "@/components/model-viewport";
import { ProgressParticleStage } from "@/components/progress-particle-stage";
import { TaskThumbnail } from "@/components/task-thumbnail";
import { Button, Card } from "@/components/ui/primitives";
import { useViewerColors } from "@/hooks/use-viewer-colors";
import { formatRelativeTime, getVisualStatus } from "@/lib/format";
import { getTaskArtifactProxyUrl } from "@/lib/task-artifacts";
import type { TaskRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

function isTerminal(status?: string) {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function GeneratePage() {
  const { t } = useTranslation();

  const getRecentStatus = (recentTask: TaskRecord): {
    label: string;
    tone: "success" | "danger" | "warning";
  } => {
    const visual = getVisualStatus(recentTask.status);
    if (visual === "done") {
      return { label: t("user.gallery.filters.completed"), tone: "success" };
    }
    if (visual === "failed") {
      return { label: t("user.gallery.filters.failed"), tone: "danger" };
    }
    return { label: `${Math.round(recentTask.progress || 0)}%`, tone: "warning" };
  };

  const desktopInputRef = useRef<HTMLInputElement | null>(null);
  const tabletInputRef = useRef<HTMLInputElement | null>(null);
  const mobileInputRef = useRef<HTMLInputElement | null>(null);
  const navigate = useNavigate();

  const [selectedModel, setSelectedModel] = useState("trellis-v2");
  const [isTabletRecentOpen, setIsTabletRecentOpen] = useState(false);

  const {
    config,
    tasks,
    currentTask,
    generate,
    generateView,
    selectFile,
    clearSelectedFile,
    submitCurrentFile,
    retryCurrentTask,
    cancelTask,
    setCurrentTaskId,
    clearCurrentTaskSelection,
  } = useGen3d();

  const recentTasks = tasks.slice(0, 20);
  const previewUrl = generate.previewDataUrl || currentTask?.previewDataUrl || "";
  const progress = generateView === "uploading"
    ? Math.max(0, Math.min(100, generate.uploadProgress || 0))
    : Math.max(0, Math.min(100, currentTask?.progress || 0));
  const isProcessing = generateView === "processing" || generateView === "uploading";
  const canCancel = Boolean(currentTask && !isTerminal(currentTask.status) && !currentTask.pendingCancel);
  const canStart = Boolean(generate.previewDataUrl) && !generate.isSubmitting && !generate.isUploading;
  const downloadUrl = getTaskArtifactProxyUrl(currentTask, config.baseUrl);
  const viewerColors = useViewerColors();
  const showCompletedActions = generateView === "completed" && Boolean(currentTask);

  useEffect(() => {
    clearCurrentTaskSelection({ lockAutoSync: true });
  }, [clearCurrentTaskSelection]);

  useEffect(() => {
    if (!isTabletRecentOpen) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsTabletRecentOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isTabletRecentOpen]);

  const handlePrimaryAction = () => {
    if (isProcessing && currentTask) {
      cancelTask(currentTask.taskId).catch(() => undefined);
      return;
    }
    submitCurrentFile().catch(() => undefined);
  };

  const renderGenerateConfigCard = (inputRef: React.RefObject<HTMLInputElement>) => (
    <Card tone="low" className="flex flex-1 flex-col border border-outline bg-surface-glass p-4 shadow-soft backdrop-blur-xl">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-muted">
        {t("user.generate.panel.title")}
      </div>

      <div className="mt-3 space-y-4">
        <div>
          <div className="mb-2 text-xs font-medium text-text-secondary">{t("user.generate.panel.uploadLabel")}</div>
          <label
            className="group relative flex h-44 cursor-pointer items-center justify-center overflow-hidden rounded-xl border border-dashed border-outline bg-surface-container-lowest transition-all duration-200 hover:border-accent hover:bg-surface-container-low"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              selectFile(event.dataTransfer.files?.[0] || null).catch(() => undefined);
            }}
          >
            <input
              ref={inputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(event) => selectFile(event.target.files?.[0] || null).catch(() => undefined)}
            />
            {previewUrl ? (
              <>
                <img src={previewUrl} alt="" className="absolute inset-0 h-full w-full object-cover" />
                <button
                  type="button"
                  className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-full bg-surface/80 text-text-primary backdrop-blur transition hover:bg-surface"
                  aria-label={t("user.generate.panel.clearImage")}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    clearSelectedFile(false);
                    if (inputRef.current) {
                      inputRef.current.value = "";
                    }
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </>
            ) : (
              <div className="grid justify-items-center gap-2.5 px-4 text-center">
                <UploadCloud className="h-7 w-7 text-text-muted" />
                <div>
                  <div className="text-sm font-medium text-text-primary">{t("user.generate.panel.uploadHint")}</div>
                  <div className="mt-1 text-xs text-text-muted">{t("user.generate.panel.fileTypes")}</div>
                </div>
              </div>
            )}
          </label>
        </div>

        <div>
          <div className="mb-2 text-xs font-medium text-text-secondary">{t("user.generate.panel.modelLabel")}</div>
          <select
            value={selectedModel}
            onChange={(event) => setSelectedModel(event.target.value)}
            className="h-10 w-full rounded-xl border border-outline bg-surface-container-low px-3 text-sm text-text-primary outline-none transition focus:border-accent"
          >
            <option value="trellis-v2">Trellis v2</option>
          </select>
        </div>

        <div className="rounded-xl border border-dashed border-outline px-3 py-2.5 text-xs text-text-muted">
          {t("user.generate.panel.comingSoon")}
        </div>
      </div>

      <div className="mt-auto pt-4">
        <Button
          variant={isProcessing ? "secondary" : "primary"}
          className="w-full justify-center"
          disabled={isProcessing ? !canCancel : !canStart}
          onClick={handlePrimaryAction}
        >
          {isProcessing ? (
            <><X className="h-4 w-4" />{t("user.generate.panel.cancelButton")}</>
          ) : (
            <><Sparkles className="h-4 w-4" />{t("user.generate.panel.generateButton")}</>
          )}
        </Button>

        {showCompletedActions ? (
          <div className="mt-2.5 space-y-2">
            {downloadUrl ? (
              <Button asChild variant="primary" className="w-full justify-center">
                <a href={downloadUrl} target="_blank" rel="noreferrer" download="model.glb">
                  <Download className="h-4 w-4" />
                  {t("user.viewer.actions.download")}
                </a>
              </Button>
            ) : null}
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                className="flex-1 justify-center"
                onClick={() => retryCurrentTask().catch(() => undefined)}
              >
                <RotateCcw className="h-4 w-4" />
                {t("user.generate.actions.retry")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="flex-1 justify-center"
                onClick={() => {
                  if (!currentTask) {
                    return;
                  }
                  navigate(`/viewer/${currentTask.taskId}`);
                }}
              >
                <Eye className="h-4 w-4" />
                {t("user.generate.actions.details")}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  );

  const renderRecentCard = (onClose?: () => void) => (
    <Card tone="low" className="flex h-full flex-col overflow-hidden border border-outline bg-surface-glass p-4 shadow-soft backdrop-blur-xl">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">{t("user.generate.recent.title")}</span>
        <div className="flex items-center gap-1.5">
          <Link
            to="/gallery"
            className="inline-flex items-center gap-0.5 text-xs text-text-muted transition hover:text-text-primary"
          >
            {t("user.gallery.filters.all")}<ArrowRight className="h-3 w-3" />
          </Link>
          {onClose ? (
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-full text-text-secondary transition hover:bg-surface-container-high hover:text-text-primary"
              aria-label={t("user.generate.panel.closeRecent")}
              onClick={onClose}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
      </div>

      <div className="mt-3 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto scrollbar-thin">
        {recentTasks.length ? (
          recentTasks.map((task) => {
            const status = getRecentStatus(task);
            const isActive = currentTask?.taskId === task.taskId;
            return (
              <button
                key={task.taskId}
                type="button"
                className={cn(
                  "flex items-center gap-2.5 rounded-xl px-2 py-2 text-left transition-all",
                  isActive
                    ? "bg-surface-container-highest"
                    : "hover:bg-surface-container",
                )}
                onClick={() => {
                  setCurrentTaskId(task.taskId);
                  onClose?.();
                }}
              >
                <TaskThumbnail task={task} variant="recent" className="h-11 w-11 shrink-0 rounded-xl" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium text-text-primary">
                    {formatRelativeTime(task.createdAt)}
                  </div>
                  <div className={cn(
                    "mt-0.5 flex items-center gap-1 text-[11px]",
                    status.tone === "success" && "text-success",
                    status.tone === "danger" && "text-danger",
                    status.tone === "warning" && "text-warning",
                  )}>
                    <span className="h-1 w-1 rounded-full bg-current" />
                    {status.label}
                  </div>
                </div>
              </button>
            );
          })
        ) : (
          <div className="py-6 text-center text-xs text-text-muted">{t("user.generate.recent.empty")}</div>
        )}
      </div>
    </Card>
  );

  return (
    <section className="relative min-h-[calc(100vh-6rem)] overflow-hidden">
      <div className="absolute inset-0 overflow-hidden bg-surface-container-lowest">
        {generateView === "idle" ? (
          <div className="flex h-full flex-col items-center justify-center px-8 text-center">
            <svg width="48" height="48" viewBox="0 0 60 60" fill="none" aria-hidden="true" className="text-text-muted">
              <rect x="10" y="24" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.5" />
              <path d="M38.5 13.5 50 33H27L38.5 13.5Z" stroke="currentColor" strokeWidth="1.5" />
              <path d="M22 18 38 34" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <div className="mt-4 text-lg font-semibold tracking-tight text-text-primary">{t("user.generate.empty.title")}</div>
            <div className="mt-1.5 text-sm text-text-muted">{t("user.generate.empty.description")}</div>
          </div>
        ) : null}

        {isProcessing ? (
          <div className="absolute inset-0">
            <ProgressParticleStage
              progress={progress}
              background={viewerColors.backgroundEdge}
              particleColor={viewerColors.textPrimary}
            />
            <div className="pointer-events-none absolute inset-x-0 bottom-8 grid justify-items-center gap-1 text-center">
              <div className="text-4xl font-bold tracking-tight text-text-primary">{progress}%</div>
              <div className="text-xs uppercase tracking-widest text-text-muted">{t("user.generate.processing.title")}</div>
            </div>
          </div>
        ) : null}

        {generateView === "completed" && currentTask ? (
          <ModelViewport
            url={downloadUrl}
            message={t("user.generate.status.modelPreparing")}
            baseUrl={config.baseUrl}
            token={config.token}
            className="absolute inset-0"
          />
        ) : null}

        {generateView === "failed" && currentTask ? (
          <div className="flex h-full flex-col items-center justify-center px-8 text-center">
            <div className="text-lg font-semibold tracking-tight text-text-primary">{t("user.generate.failed.title")}</div>
            <div className="mt-1.5 max-w-sm text-sm text-text-muted">
              {currentTask.error?.message || currentTask.note || t("user.generate.failed.fallback")}
            </div>
            <button
              type="button"
              className="mt-5 inline-flex items-center gap-1.5 rounded-full border border-outline px-4 py-2 text-xs font-medium text-text-secondary transition hover:bg-surface-container-high hover:text-text-primary"
              onClick={() => retryCurrentTask().catch(() => undefined)}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              {t("user.generate.failed.retry")}
            </button>
          </div>
        ) : null}
      </div>

      <div className="pointer-events-none relative z-10 hidden min-h-[calc(100vh-6rem)] md:block">
        <div className="hidden min-h-[calc(100vh-6rem)] gap-4 py-2 xl:grid xl:grid-cols-[300px_minmax(0,1fr)_300px]">
          <aside className="pointer-events-auto flex flex-col xl:sticky xl:top-20 xl:max-h-[calc(100vh-6.5rem)]">
            {renderGenerateConfigCard(desktopInputRef)}
          </aside>

          <div />

          <aside className="pointer-events-auto flex flex-col xl:sticky xl:top-20 xl:max-h-[calc(100vh-6.5rem)]">
            {renderRecentCard()}
          </aside>
        </div>

        <div className="relative hidden min-h-[calc(100vh-6rem)] xl:hidden md:block">
          <aside className="pointer-events-auto absolute bottom-4 left-4 top-4 z-20 w-[300px]">
            {renderGenerateConfigCard(tabletInputRef)}
          </aside>

          <button
            type="button"
            className="pointer-events-auto absolute right-4 top-1/2 z-20 inline-flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-outline bg-surface-glass text-text-primary shadow-float backdrop-blur-xl transition hover:bg-surface-container-high"
            aria-label={t("user.generate.panel.openRecent")}
            title={t("user.generate.panel.openRecent")}
            onClick={() => setIsTabletRecentOpen(true)}
          >
            <History className="h-4 w-4" />
          </button>

          <button
            type="button"
            className={cn(
              "pointer-events-auto absolute inset-0 z-20 bg-background/20 transition",
              isTabletRecentOpen ? "opacity-100" : "pointer-events-none opacity-0",
            )}
            aria-label={t("user.generate.panel.closeRecent")}
            onClick={() => setIsTabletRecentOpen(false)}
          />

          <div
            className={cn(
              "pointer-events-auto absolute bottom-4 right-4 top-4 z-30 w-[300px] transform-gpu transition duration-200",
              isTabletRecentOpen ? "translate-x-0 opacity-100" : "translate-x-[110%] opacity-0",
            )}
          >
            {renderRecentCard(() => setIsTabletRecentOpen(false))}
          </div>
        </div>
      </div>

      <div className="pointer-events-auto relative z-10 mt-3 grid gap-3 px-3 pb-3 md:hidden">
        {renderGenerateConfigCard(mobileInputRef)}
        {renderRecentCard()}
      </div>
    </section>
  );
}
