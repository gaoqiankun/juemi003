import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Download, X } from "lucide-react";

import { ThreeViewer } from "@/components/three-viewer";
import { TaskStatusBadge } from "@/components/task-status-badge";
import { useGen3d } from "@/app/gen3d-provider";
import { Button } from "@/components/ui/button";
import { useViewerColors } from "@/hooks/use-viewer-colors";
import { formatTime } from "@/lib/format";
import { getTaskArtifactProxyUrl } from "@/lib/task-artifacts";
import type { TaskRecord } from "@/lib/types";

export function TaskSheet({
  task,
  open,
  onOpenChange,
  onDeleteRequest,
}: {
  task: TaskRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleteRequest: (taskId: string) => void;
}) {
  const { config } = useGen3d();
  const viewerUrl = getTaskArtifactProxyUrl(task, config.baseUrl);
  const viewerColors = useViewerColors();

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[color:color-mix(in_srgb,var(--surface)_84%,transparent)] backdrop-blur-sm" />
        <DialogPrimitive.Content className="fixed inset-0 z-50 bg-transparent focus:outline-none">
          <DialogPrimitive.Close
            className="absolute right-5 top-5 z-20 flex h-10 w-10 items-center justify-center rounded-full border border-outline bg-surface-glass text-text-secondary shadow-float backdrop-blur-xl transition hover:bg-surface-container-high hover:text-text-primary"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </DialogPrimitive.Close>

          {task ? (
            <div className="grid h-full grid-cols-1 lg:grid-cols-[minmax(0,65fr)_minmax(360px,35fr)]">
              <div className="min-w-0 bg-surface-container-lowest">
                <ThreeViewer
                  url={viewerUrl}
                  message="模型准备中"
                  baseUrl={config.baseUrl}
                  token={config.token}
                  backgroundCenter={viewerColors.backgroundCenter}
                  backgroundEdge={viewerColors.backgroundEdge}
                  className="rounded-none bg-surface-container-lowest"
                />
              </div>

              <div className="flex min-w-0 flex-col bg-surface-container-low p-6">
                <div className="space-y-6">
                  <TaskStatusBadge task={task} />
                  <div className="space-y-2">
                    <div className="text-[12px] text-text-muted">创建时间</div>
                    <div className="text-[14px] text-text-primary">{formatTime(task.createdAt)}</div>
                  </div>
                </div>

                <div className="mt-10">
                  <Button
                    asChild
                    className="h-11 w-full rounded-[10px]"
                  >
                    <a
                      href={viewerUrl || "#"}
                      target="_blank"
                      rel="noreferrer"
                      download="model.glb"
                      className={!viewerUrl ? "pointer-events-none opacity-50" : ""}
                    >
                      <Download className="h-4 w-4" />
                      下载模型
                    </a>
                  </Button>
                </div>

                <div className="mt-auto">
                  <button
                    type="button"
                    className="inline-flex h-10 items-center justify-center rounded-[10px] border border-[color:color-mix(in_srgb,var(--danger)_24%,transparent)] bg-[color:color-mix(in_srgb,var(--danger)_10%,transparent)] px-3 text-[14px] font-medium text-danger-text transition hover:bg-[color:color-mix(in_srgb,var(--danger)_16%,transparent)]"
                    onClick={() => onDeleteRequest(task.taskId)}
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
