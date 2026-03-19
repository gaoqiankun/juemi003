import { ArrowRight, Download, RotateCcw, Sparkles, UploadCloud, X } from "lucide-react";
import { useRef } from "react";
import { Link } from "react-router-dom";

import { useGen3d } from "@/app/gen3d-provider";
import { ProgressParticleStage } from "@/components/progress-particle-stage";
import { TaskThumbnail } from "@/components/task-thumbnail";
import { ThreeViewer } from "@/components/three-viewer";
import { Button } from "@/components/ui/button";
import { formatRelativeTime, getVisualStatus } from "@/lib/format";
import { getTaskArtifactProxyUrl } from "@/lib/task-artifacts";
import { cn } from "@/lib/utils";
import type { TaskRecord } from "@/lib/types";

function isTerminal(status?: string) {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

function EmptyStateGlyph() {
  return (
    <svg width="60" height="60" viewBox="0 0 60 60" fill="none" aria-hidden="true" className="text-white">
      <rect x="10" y="24" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M38.5 13.5 50 33H27L38.5 13.5Z" stroke="currentColor" strokeWidth="1.5" />
      <path d="M22 18 38 34" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function getRecentStatus(task: TaskRecord) {
  const visual = getVisualStatus(task.status);
  if (visual === "done") {
    return {
      label: "已完成",
      className: "text-[#16a34a]",
      dotClassName: "bg-[#16a34a]",
    };
  }
  if (visual === "failed") {
    return {
      label: "失败",
      className: "text-[#dc2626]",
      dotClassName: "bg-[#dc2626]",
    };
  }
  return {
    label: `生成中 ${Math.round(task.progress || 0)}%`,
    className: "text-[#ca8a04]",
    dotClassName: "bg-[#ca8a04]",
  };
}

function RecentTaskStatus({ task }: { task: TaskRecord }) {
  const status = getRecentStatus(task);

  return (
    <div className={cn("inline-flex items-center gap-2 text-[13px]", status.className)}>
      <span className={cn("h-2 w-2 rounded-full", status.dotClassName)} />
      <span>{status.label}</span>
    </div>
  );
}

export function GeneratePage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const {
    config,
    tasks,
    generate,
    currentTask,
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

  const handlePrimaryAction = () => {
    if (isProcessing && currentTask) {
      cancelTask(currentTask.taskId).catch(() => undefined);
      return;
    }
    submitCurrentFile().catch(() => undefined);
  };

  return (
    <section className="min-h-[calc(100vh-48px)] bg-[#000000]">
      <div className="grid min-h-[calc(100vh-48px)] grid-cols-1 bg-[#000000] xl:grid-cols-[220px_minmax(0,1fr)_280px]">
        <aside className="border-b border-[#1a1a1a] bg-[#0f0f0f] xl:border-b-0 xl:border-r">
          <div className="flex h-full flex-col px-4 py-4">
            <div className="text-[12px] text-[#666666]">图像</div>

            <label
              className="relative mt-4 flex h-[180px] w-[180px] cursor-pointer items-center justify-center overflow-hidden rounded-[8px] border border-dashed border-[#333333] bg-[#1a1a1a]"
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
                  <img src={previewUrl} alt="上传图片" className="absolute inset-0 size-full object-cover" />
                  <button
                    type="button"
                    className="absolute right-2 top-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-black/55 text-white transition hover:bg-black/75"
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
                <div className="flex flex-col items-center justify-center gap-3 px-4 text-center">
                  <UploadCloud className="h-7 w-7 text-white/82" />
                  <div className="text-[13px] text-[#ffffff]">点击或拖拽上传</div>
                </div>
              )}
            </label>

            <div className="mt-3 w-[180px] text-center text-[12px] text-[#555555]">JPG · PNG · WEBP</div>

            <div className="mt-auto pt-6">
              <Button
                className={cn(
                  "h-11 w-full rounded-[8px] border text-[14px] font-medium shadow-none",
                  isProcessing
                    ? "border-[#333333] bg-[#1f1f1f] text-white hover:bg-[#262626]"
                    : "border-[#16a34a] bg-[#16a34a] text-white hover:bg-[#15803d]",
                )}
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
          </div>
        </aside>

        <div className="min-h-[420px] bg-[#000000] xl:min-h-[calc(100vh-48px)]">
          {generateView === "idle" ? (
            <div className="flex h-full min-h-[420px] flex-col items-center justify-center px-8 text-center xl:min-h-[calc(100vh-48px)]">
              <EmptyStateGlyph />
              <div className="mt-6 text-[20px] font-medium text-white">今天你会创造什么？</div>
              <div className="mt-3 text-[14px] text-[#666666]">上传一张图片，几分钟内生成可下载的 3D 模型</div>
            </div>
          ) : null}

          {isProcessing ? (
            <div className="relative h-full min-h-[420px] overflow-hidden bg-[#000000] xl:min-h-[calc(100vh-48px)]">
              <ProgressParticleStage progress={progress} />
              <div className="pointer-events-none absolute inset-x-0 bottom-12 flex flex-col items-center gap-2">
                <div className="text-[40px] font-bold leading-none text-white">{progress}%</div>
                <div className="text-[14px] text-[#888888]">生成中</div>
              </div>
            </div>
          ) : null}

          {generateView === "completed" && currentTask ? (
            <div className="flex h-full min-h-[420px] flex-col bg-[#1a1a1a] xl:min-h-[calc(100vh-48px)]">
              <div className="min-h-0 flex-1">
                <ThreeViewer
                  url={downloadUrl}
                  message="模型准备中"
                  baseUrl={config.baseUrl}
                  token={config.token}
                  background="#1a1a1a"
                  className="rounded-none bg-[#1a1a1a]"
                />
              </div>

              <div className="flex h-11 items-center justify-between border-t border-[#222222] bg-[#111111] px-4">
                <div className="text-[12px] text-[#888888]">
                  <span className="text-white">模型已就绪</span>
                  <span className="mx-2 text-[#444444]">·</span>
                  <span>{currentTaskInfo}</span>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    asChild
                    className="h-9 rounded-[8px] border border-white bg-white px-4 text-black shadow-none hover:bg-[#f1f1f1]"
                  >
                    <a
                      href={downloadUrl || "#"}
                      target="_blank"
                      rel="noreferrer"
                      download="model.glb"
                      className={!downloadUrl ? "pointer-events-none opacity-50" : ""}
                    >
                      <Download className="h-4 w-4" />
                      下载
                    </a>
                  </Button>
                  <Button
                    variant="outline"
                    className="h-9 rounded-[8px] border-[#333333] bg-[#1f1f1f] px-4 text-white hover:bg-[#262626]"
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
            <div className="flex h-full min-h-[420px] flex-col items-center justify-center px-8 text-center xl:min-h-[calc(100vh-48px)]">
              <EmptyStateGlyph />
              <div className="mt-6 text-[20px] font-medium text-white">这次生成没有完成</div>
              <div className="mt-3 max-w-[420px] text-[14px] text-[#666666]">
                {currentTask.error?.message || currentTask.note || "请重新上传一张图片后再试一次。"}
              </div>
              <Button
                variant="outline"
                className="mt-8 h-11 rounded-[8px] border-[#333333] bg-[#1f1f1f] px-5 text-white hover:bg-[#262626]"
                onClick={() => retryCurrentTask().catch(() => undefined)}
              >
                <RotateCcw className="h-4 w-4" />
                重新生成
              </Button>
            </div>
          ) : null}
        </div>

        <aside className="flex min-h-[320px] flex-col border-t border-[#1a1a1a] bg-[#0a0a0a] xl:min-h-[calc(100vh-48px)] xl:border-l xl:border-t-0">
          <div className="flex h-10 items-center justify-between px-4">
            <span className="text-[13px] text-[#888888]">最近生成</span>
            <Link to="/gallery" className="inline-flex items-center gap-1 text-[13px] text-[#888888] transition hover:text-white">
              查看全部
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
            {recentTasks.length ? (
              recentTasks.map((task) => (
                <button
                  key={task.taskId}
                  type="button"
                  className={cn(
                    "flex h-[72px] w-full items-center gap-3 px-4 text-left transition hover:bg-[#141414]",
                    currentTask?.taskId === task.taskId && "bg-[#141414]",
                  )}
                  onClick={() => setCurrentTaskId(task.taskId)}
                >
                  <TaskThumbnail task={task} variant="recent" className="h-14 w-14 rounded-[6px] bg-[#1a1a1a]" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] text-white">{formatRelativeTime(task.createdAt)}</div>
                    <div className="mt-1">
                      <RecentTaskStatus task={task} />
                    </div>
                  </div>
                </button>
              ))
            ) : (
              <div className="px-4 py-6 text-[13px] text-[#444444]">还没有生成记录</div>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
