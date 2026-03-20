import { ArrowRight, Download, RotateCcw, Sparkles, UploadCloud, X } from "lucide-react";
import { useMemo, useRef } from "react";
import { Link } from "react-router-dom";

import { useGen3d } from "@/app/gen3d-provider";
import { ProgressParticleStage } from "@/components/progress-particle-stage";
import { TaskThumbnail } from "@/components/task-thumbnail";
import { ThreeViewer } from "@/components/three-viewer";
import { Button, Card } from "@/components/ui/primitives";
import { useTheme } from "@/hooks/use-theme";
import { formatRelativeTime, getVisualStatus } from "@/lib/format";
import { getTaskArtifactProxyUrl } from "@/lib/task-artifacts";
import type { TaskRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

function isTerminal(status?: string) {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

function EmptyStateGlyph() {
  return (
    <svg width="60" height="60" viewBox="0 0 60 60" fill="none" aria-hidden="true" className="text-text-primary">
      <rect x="10" y="24" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M38.5 13.5 50 33H27L38.5 13.5Z" stroke="currentColor" strokeWidth="1.5" />
      <path d="M22 18 38 34" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function getRecentStatus(task: TaskRecord): {
  label: string;
  tone: "success" | "danger" | "warning";
} {
  const visual = getVisualStatus(task.status);
  if (visual === "done") {
    return {
      label: "已完成",
      tone: "success",
    };
  }
  if (visual === "failed") {
    return {
      label: "失败",
      tone: "danger",
    };
  }
  return {
    label: `生成中 ${Math.round(task.progress || 0)}%`,
    tone: "warning",
  };
}

function RecentTaskStatus({ task }: { task: TaskRecord }) {
  const status = getRecentStatus(task);

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 text-xs font-medium",
        {
          "text-success-text": status.tone === "success",
          "text-danger-text": status.tone === "danger",
          "text-warning-text": status.tone === "warning",
        },
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      <span>{status.label}</span>
    </div>
  );
}

const eyebrowClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";

export function GeneratePage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { theme } = useTheme();
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
  } = useGen3d();

  const recentTasks = tasks.slice(0, 12);
  const previewUrl = generate.previewDataUrl || currentTask?.previewDataUrl || "";
  const progress = generateView === "uploading"
    ? Math.max(0, Math.min(100, generate.uploadProgress || 0))
    : Math.max(0, Math.min(100, currentTask?.progress || 0));
  const isProcessing = generateView === "processing" || generateView === "uploading";
  const canCancel = Boolean(currentTask && !isTerminal(currentTask.status) && !currentTask.pendingCancel);
  const canStart = Boolean(generate.previewDataUrl) && !generate.isSubmitting && !generate.isUploading;
  const downloadUrl = getTaskArtifactProxyUrl(currentTask, config.baseUrl);
  const currentTaskInfo = currentTask?.artifacts?.[0]?.type?.toUpperCase() || "GLB";
  const viewerBackground = useMemo(() => {
    if (typeof window === "undefined") {
      return theme === "light" ? "#ffffff" : "#16161a";
    }

    return getComputedStyle(document.documentElement).getPropertyValue("--surface-container-lowest").trim()
      || (theme === "light" ? "#ffffff" : "#16161a");
  }, [theme]);
  const stageParticleColor = useMemo(() => {
    if (typeof window === "undefined") {
      return theme === "light" ? "#1a1c1d" : "#f5f7fa";
    }

    return getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim()
      || (theme === "light" ? "#1a1c1d" : "#f5f7fa");
  }, [theme]);

  const handlePrimaryAction = () => {
    if (isProcessing && currentTask) {
      cancelTask(currentTask.taskId).catch(() => undefined);
      return;
    }
    submitCurrentFile().catch(() => undefined);
  };

  return (
    <section className="grid gap-5 xl:grid-cols-[320px_minmax(0,1fr)_320px]">
      <aside className="xl:sticky xl:top-24 xl:h-[calc(100vh-8.5rem)]">
        <Card tone="low" className="flex h-full flex-col p-5">
          <div className={eyebrowClassName}>图像</div>

          <label
            className="group relative mt-4 flex aspect-[4/5] w-full cursor-pointer items-center justify-center overflow-hidden rounded-[24px] border border-dashed border-outline bg-surface-container-lowest p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-accent hover:bg-surface-container-low"
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
                <img src={previewUrl} alt="上传图片" className="absolute inset-0 h-full w-full object-cover" />
                <button
                  type="button"
                  className="absolute right-3 top-3 inline-flex h-9 w-9 items-center justify-center rounded-full border border-outline bg-surface text-text-primary shadow-float transition hover:bg-surface-container-high"
                  aria-label="清除已选图片"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    clearSelectedFile(false);
                    if (inputRef.current) {
                      inputRef.current.value = "";
                    }
                  }}
                >
                  <X className="h-4 w-4" />
                </button>
              </>
            ) : (
              <div className="grid justify-items-center gap-4 text-center">
                <span className="inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-outline bg-surface-container text-accent-strong">
                  <UploadCloud className="h-6 w-6" />
                </span>
                <div className="grid gap-2">
                  <div className="text-base font-semibold tracking-[-0.02em] text-text-primary">点击或拖拽上传</div>
                  <div className="text-sm leading-6 text-text-secondary">支持 JPG、PNG、WEBP，建议使用主体清晰的正视图</div>
                </div>
              </div>
            )}
          </label>

          <div className="mt-4 text-center text-sm text-text-muted">JPG · PNG · WEBP</div>

          <div className="mt-auto pt-6">
            <Button
              variant={isProcessing ? "secondary" : "primary"}
              className="w-full justify-center"
              disabled={isProcessing ? !canCancel : !canStart}
              onClick={handlePrimaryAction}
            >
              {isProcessing ? (
                <>
                  <X className="h-4 w-4" />
                  取消
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  生成
                </>
              )}
            </Button>
          </div>
        </Card>
      </aside>

      <Card className="min-h-[640px] overflow-hidden p-0">
        {generateView === "idle" ? (
          <div className="flex h-full min-h-[640px] flex-col items-center justify-center bg-[image:var(--page-gradient)] bg-surface-container-low px-8 text-center">
            <EmptyStateGlyph />
            <div className="mt-5 text-3xl font-semibold tracking-[-0.04em] text-text-primary">今天你会创造什么？</div>
            <div className="mt-3 max-w-xl text-sm leading-7 text-text-secondary">
              上传一张图片，几分钟内生成可下载的 3D 模型
            </div>
          </div>
        ) : null}

        {isProcessing ? (
          <div className="relative min-h-[640px] overflow-hidden bg-surface-container-lowest">
            <ProgressParticleStage
              progress={progress}
              background={viewerBackground}
              particleColor={stageParticleColor}
            />
            <div className="pointer-events-none absolute inset-x-0 bottom-10 grid justify-items-center gap-2 px-6 text-center">
              <div className="text-[clamp(3rem,7vw,4.5rem)] font-semibold tracking-[-0.05em] text-text-primary">
                {progress}%
              </div>
              <div className="text-sm uppercase tracking-[0.16em] text-text-secondary">生成中</div>
            </div>
          </div>
        ) : null}

        {generateView === "completed" && currentTask ? (
          <div className="grid min-h-[640px] grid-rows-[minmax(0,1fr)_auto]">
            <div className="min-h-0 bg-surface-container-lowest">
              <ThreeViewer
                url={downloadUrl}
                message="模型准备中"
                baseUrl={config.baseUrl}
                token={config.token}
                background={viewerBackground}
                className="!rounded-none !bg-transparent"
              />
            </div>

            <div className="flex flex-col gap-4 border-t border-outline bg-surface-container px-5 py-4 md:flex-row md:items-center md:justify-between">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-text-primary">模型已就绪</div>
                <div className="mt-1 text-sm text-text-secondary">{currentTaskInfo} 已准备好下载或重新生成</div>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button variant="primary" asChild>
                  <a
                    href={downloadUrl || "#"}
                    target="_blank"
                    rel="noreferrer"
                    download="model.glb"
                    className={!downloadUrl ? "pointer-events-none opacity-50" : undefined}
                  >
                    <Download className="h-4 w-4" />
                    下载
                  </a>
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => retryCurrentTask().catch(() => undefined)}
                >
                  <RotateCcw className="h-4 w-4" />
                  重新生成
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {generateView === "failed" && currentTask ? (
          <div className="flex min-h-[640px] flex-col items-center justify-center bg-[image:var(--page-gradient)] bg-surface-container-low px-8 text-center">
            <EmptyStateGlyph />
            <div className="mt-5 text-3xl font-semibold tracking-[-0.04em] text-text-primary">这次生成没有完成</div>
            <div className="mt-3 max-w-xl text-sm leading-7 text-text-secondary">
              {currentTask.error?.message || currentTask.note || "请重新上传一张图片后再试一次。"}
            </div>
            <Button
              variant="secondary"
              className="mt-8"
              onClick={() => retryCurrentTask().catch(() => undefined)}
            >
              <RotateCcw className="h-4 w-4" />
              重新生成
            </Button>
          </div>
        ) : null}
      </Card>

      <aside className="xl:sticky xl:top-24 xl:h-[calc(100vh-8.5rem)]">
        <Card tone="low" className="flex h-full flex-col p-5">
          <div className="flex items-center justify-between gap-3">
            <div className={eyebrowClassName}>最近生成</div>
            <Link
              to="/gallery"
              className="inline-flex items-center gap-1 text-sm text-text-secondary transition-colors hover:text-text-primary"
            >
              查看全部
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>

          <div className="mt-5 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1 scrollbar-thin">
            {recentTasks.length ? (
              recentTasks.map((task) => (
                <button
                  key={task.taskId}
                  type="button"
                  className={cn(
                    "flex items-center gap-3 rounded-2xl border px-3 py-3 text-left transition-all duration-200",
                    currentTask?.taskId === task.taskId
                      ? "border-outline bg-surface-container-highest shadow-float"
                      : "border-transparent bg-transparent hover:border-outline hover:bg-surface-container",
                  )}
                  onClick={() => setCurrentTaskId(task.taskId)}
                >
                  <TaskThumbnail task={task} variant="recent" className="h-16 w-16 shrink-0 rounded-2xl" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-text-primary">
                      {formatRelativeTime(task.createdAt)}
                    </div>
                    <div className="mt-2">
                      <RecentTaskStatus task={task} />
                    </div>
                  </div>
                </button>
              ))
            ) : (
              <div className="rounded-2xl border border-outline bg-surface-container px-4 py-5 text-sm text-text-muted">
                还没有生成记录
              </div>
            )}
          </div>
        </Card>
      </aside>
    </section>
  );
}
