import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Download, X } from "lucide-react";

import { ThreeViewer } from "@/components/three-viewer";
import { TaskStatusBadge } from "@/components/task-status-badge";
import { useGen3d } from "@/app/gen3d-provider";
import { Button } from "@/components/ui/button";
import { formatTime } from "@/lib/format";
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
  const viewerUrl = task?.resolvedArtifactUrl || task?.rawArtifactUrl || "";

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[rgba(0,0,0,0.95)]" />
        <DialogPrimitive.Content className="fixed inset-0 z-50 bg-transparent focus:outline-none">
          <DialogPrimitive.Close className="absolute right-5 top-5 z-20 flex h-10 w-10 items-center justify-center rounded-full border border-[#2a2a2a] bg-black/50 text-white/72 transition hover:bg-black/70 hover:text-white">
            <X className="h-4 w-4" />
          </DialogPrimitive.Close>

          {task ? (
            <div className="grid h-full grid-cols-1 lg:grid-cols-[minmax(0,65fr)_minmax(360px,35fr)]">
              <div className="min-w-0 bg-[#1a1a1a]">
                <ThreeViewer
                  url={viewerUrl}
                  message="模型准备中"
                  baseUrl={config.baseUrl}
                  token={config.token}
                  background="#1a1a1a"
                  className="rounded-none bg-[#1a1a1a]"
                />
              </div>

              <div className="flex min-w-0 flex-col bg-[#0f0f0f] p-6">
                <div className="space-y-6">
                  <TaskStatusBadge task={task} />
                  <div className="space-y-2">
                    <div className="text-[12px] text-[#888888]">创建时间</div>
                    <div className="text-[14px] text-white">{formatTime(task.createdAt)}</div>
                  </div>
                </div>

                <div className="mt-10">
                  <Button
                    asChild
                    className="h-11 w-full rounded-[8px] bg-white text-black shadow-none hover:bg-[#f1f1f1]"
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
                    className="text-[14px] text-[#dc2626] transition hover:text-[#ef4444]"
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
