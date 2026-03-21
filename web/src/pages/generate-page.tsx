import { ArrowRight, Download, Eye, RotateCcw, Sparkles, UploadCloud, X } from "lucide-react";
import { useEffect, useRef } from "react";
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

function getRecentStatus(task: TaskRecord): {
  label: string;
  tone: "success" | "danger" | "warning";
} {
  const visual = getVisualStatus(task.status);
  if (visual === "done") {
    return { label: "已完成", tone: "success" };
  }
  if (visual === "failed") {
    return { label: "失败", tone: "danger" };
  }
  return { label: `${Math.round(task.progress || 0)}%`, tone: "warning" };
}

export function GeneratePage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const navigate = useNavigate();
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

  useEffect(() => {
    clearCurrentTaskSelection({ lockAutoSync: true });
  }, [clearCurrentTaskSelection]);

  const handlePrimaryAction = () => {
    if (isProcessing && currentTask) {
      cancelTask(currentTask.taskId).catch(() => undefined);
      return;
    }
    submitCurrentFile().catch(() => undefined);
  };

  return (
    <section className="grid min-h-[calc(100vh-6rem)] gap-3 xl:grid-cols-[280px_minmax(0,1fr)_280px]">
      {/* ── Left: Upload + Generate ── */}
      <aside className="flex flex-col gap-3 xl:sticky xl:top-20 xl:max-h-[calc(100vh-6.5rem)]">
        <Card tone="low" className="flex flex-1 flex-col p-4">
          <label
            className="group relative flex flex-1 cursor-pointer items-center justify-center overflow-hidden rounded-2xl border border-dashed border-outline bg-surface-container-lowest transition-all duration-200 hover:border-accent hover:bg-surface-container-low"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); selectFile(e.dataTransfer.files?.[0] || null).catch(() => undefined); }}
          >
            <input
              ref={inputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => selectFile(e.target.files?.[0] || null).catch(() => undefined)}
            />
            {previewUrl ? (
              <>
                <img src={previewUrl} alt="" className="absolute inset-0 h-full w-full object-cover" />
                <button
                  type="button"
                  className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-full bg-surface/80 text-text-primary backdrop-blur transition hover:bg-surface"
                  aria-label="清除"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); clearSelectedFile(false); if (inputRef.current) inputRef.current.value = ""; }}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </>
            ) : (
              <div className="grid justify-items-center gap-3 p-6 text-center">
                <UploadCloud className="h-8 w-8 text-text-muted" />
                <div>
                  <div className="text-sm font-medium text-text-primary">点击或拖拽上传</div>
                  <div className="mt-1 text-xs leading-5 text-text-muted">JPG / PNG / WEBP</div>
                </div>
              </div>
            )}
          </label>

          <div className="mt-3">
            <Button
              variant={isProcessing ? "secondary" : "primary"}
              className="w-full justify-center"
              disabled={isProcessing ? !canCancel : !canStart}
              onClick={handlePrimaryAction}
            >
              {isProcessing ? (
                <><X className="h-4 w-4" />取消</>
              ) : (
                <><Sparkles className="h-4 w-4" />生成</>
              )}
            </Button>
          </div>
        </Card>
      </aside>

      {/* ── Center: Viewport ── */}
      <div className="relative min-h-[32rem] overflow-hidden rounded-2xl border border-outline bg-surface-container-lowest">
        {generateView === "idle" ? (
          <div className="flex h-full flex-col items-center justify-center px-8 text-center">
            <svg width="48" height="48" viewBox="0 0 60 60" fill="none" aria-hidden="true" className="text-text-muted">
              <rect x="10" y="24" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.5" />
              <path d="M38.5 13.5 50 33H27L38.5 13.5Z" stroke="currentColor" strokeWidth="1.5" />
              <path d="M22 18 38 34" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <div className="mt-4 text-lg font-semibold tracking-tight text-text-primary">上传图片开始创作</div>
            <div className="mt-1.5 text-sm text-text-muted">几分钟内生成可下载的 3D 模型</div>
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
              <div className="text-xs uppercase tracking-widest text-text-muted">生成中</div>
            </div>
          </div>
        ) : null}

        {generateView === "completed" && currentTask ? (
          <>
            <ModelViewport
              url={downloadUrl}
              message="模型准备中"
              baseUrl={config.baseUrl}
              token={config.token}
              className="absolute inset-0"
            />
            {/* Floating action bar */}
            <div className="absolute bottom-5 left-1/2 z-10 -translate-x-1/2">
              <div className="flex items-center gap-1.5 rounded-full border border-outline bg-surface-glass p-1.5 shadow-float backdrop-blur-xl">
                {downloadUrl ? (
                  <a
                    href={downloadUrl}
                    target="_blank"
                    rel="noreferrer"
                    download="model.glb"
                    className="inline-flex h-9 items-center gap-1.5 rounded-full bg-accent px-4 text-xs font-semibold text-accent-ink transition hover:bg-accent-deep"
                  >
                    <Download className="h-3.5 w-3.5" />
                    下载
                  </a>
                ) : null}
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-medium text-text-secondary transition hover:bg-surface-container-highest hover:text-text-primary"
                  onClick={() => retryCurrentTask().catch(() => undefined)}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  重试
                </button>
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-medium text-text-secondary transition hover:bg-surface-container-highest hover:text-text-primary"
                  onClick={() => navigate(`/viewer/${currentTask.taskId}`)}
                >
                  <Eye className="h-3.5 w-3.5" />
                  详情
                </button>
              </div>
            </div>
          </>
        ) : null}

        {generateView === "failed" && currentTask ? (
          <div className="flex h-full flex-col items-center justify-center px-8 text-center">
            <div className="text-lg font-semibold tracking-tight text-text-primary">生成未完成</div>
            <div className="mt-1.5 max-w-sm text-sm text-text-muted">
              {currentTask.error?.message || currentTask.note || "请重新上传后再试"}
            </div>
            <button
              type="button"
              className="mt-5 inline-flex items-center gap-1.5 rounded-full border border-outline px-4 py-2 text-xs font-medium text-text-secondary transition hover:bg-surface-container-high hover:text-text-primary"
              onClick={() => retryCurrentTask().catch(() => undefined)}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              重新生成
            </button>
          </div>
        ) : null}
      </div>

      {/* ── Right: Recent ── */}
      <aside className="flex flex-col gap-3 xl:sticky xl:top-20 xl:max-h-[calc(100vh-6.5rem)]">
        <Card tone="low" className="flex flex-1 flex-col overflow-hidden p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">最近生成</span>
            <Link
              to="/gallery"
              className="inline-flex items-center gap-0.5 text-xs text-text-muted transition hover:text-text-primary"
            >
              全部<ArrowRight className="h-3 w-3" />
            </Link>
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
                    onClick={() => setCurrentTaskId(task.taskId)}
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
              <div className="py-6 text-center text-xs text-text-muted">暂无记录</div>
            )}
          </div>
        </Card>
      </aside>
    </section>
  );
}
