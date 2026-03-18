import { Download, GalleryHorizontalEnd, RefreshCcw, Trash2 } from "lucide-react";

import { canCancelTask, useGen3d } from "@/app/gen3d-provider";
import { ThreeViewer } from "@/components/three-viewer";
import { TaskStatusBadge } from "@/components/task-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { formatStage, formatTime, getTaskShortId } from "@/lib/format";
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
  const { cancelTask, config, refreshTask, subscribeToTask } = useGen3d();

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto">
        {task ? (
          <>
            <SheetHeader className="pr-16">
              <SheetTitle>任务 {getTaskShortId(task.taskId)}</SheetTitle>
              <SheetDescription>
                详细查看任务状态、Three.js 预览、下载地址与操作入口。
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-6 p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <TaskStatusBadge task={task} />
                <div className="text-sm text-slate-400">{formatTime(task.createdAt)}</div>
              </div>

              <div className="h-[340px] overflow-hidden rounded-[28px] border border-white/10 bg-slate-950">
                <ThreeViewer
                  url={task.resolvedArtifactUrl}
                  message={task.status === "succeeded" ? "模型文件正在补拉中…" : "任务完成后会自动加载 3D 预览。"}
                  baseUrl={config.baseUrl}
                  token={config.token}
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <CardContent className="space-y-3 p-5">
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Task ID</div>
                      <div className="mt-2 text-sm text-white">{task.taskId}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Current Stage</div>
                      <div className="mt-2 text-sm text-white">{formatStage(task.currentStage || task.status)}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Transport</div>
                      <div className="mt-2 text-sm text-white">{task.transport}</div>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardContent className="space-y-3 p-5">
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Artifact</div>
                      <div className="mt-2 text-sm text-white break-all">{task.resolvedArtifactUrl || task.rawArtifactUrl || "等待生成"}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Updated</div>
                      <div className="mt-2 text-sm text-white">{formatTime(task.updatedAt || task.lastSeenAt)}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Model</div>
                      <div className="mt-2 text-sm text-white">{task.model}</div>
                    </div>
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardContent className="p-5">
                  <div className="flex flex-wrap gap-3">
                    <Button
                      variant="secondary"
                      asChild
                    >
                      <a
                        href={task.resolvedArtifactUrl || "#"}
                        target="_blank"
                        rel="noreferrer"
                        download="model.glb"
                        className={!task.resolvedArtifactUrl ? "pointer-events-none opacity-50" : ""}
                      >
                        <Download className="h-4 w-4" />
                        下载模型
                      </a>
                    </Button>
                    <Button variant="outline" onClick={() => refreshTask(task.taskId, { silent: false })}>
                      <RefreshCcw className="h-4 w-4" />
                      刷新详情
                    </Button>
                    <Button
                      variant="outline"
                      disabled={!canCancelTask(task)}
                      onClick={() => cancelTask(task.taskId).catch(() => undefined)}
                    >
                      <GalleryHorizontalEnd className="h-4 w-4" />
                      {canCancelTask(task) ? "取消任务" : "当前阶段不可取消"}
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={task.pendingDelete}
                      onClick={() => onDeleteRequest(task.taskId)}
                    >
                      <Trash2 className="h-4 w-4" />
                      删除任务
                    </Button>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-display text-lg font-semibold text-white">Live Logs</div>
                      <div className="mt-1 text-sm text-slate-400">最近 30 条任务事件，终态任务也会保留事件轨迹。</div>
                    </div>
                    {task.status !== "succeeded" && task.status !== "failed" && task.status !== "cancelled" ? (
                      <Button variant="ghost" size="sm" onClick={() => subscribeToTask(task.taskId, true).catch(() => undefined)}>
                        恢复订阅
                      </Button>
                    ) : null}
                  </div>
                  <div className="mt-5 space-y-3">
                    {task.events.length ? task.events.slice().reverse().map((event) => (
                      <div key={`${event.timestamp}-${event.event}-${event.progress}`} className="rounded-[22px] border border-white/10 bg-white/5 px-4 py-3">
                        <div className="flex items-center justify-between gap-3">
                          <strong className="text-sm text-white">{event.event}</strong>
                          <span className="text-xs text-slate-500">{formatTime(event.timestamp)}</span>
                        </div>
                        <div className="mt-2 text-sm text-slate-300">状态：{event.status} · 阶段：{formatStage(event.currentStage)}</div>
                        <div className="mt-1 text-xs text-slate-500">进度 {event.progress}% · 来源 {event.source}{event.message ? ` · ${event.message}` : ""}</div>
                      </div>
                    )) : (
                      <div className="rounded-[22px] border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-400">
                        暂无事件日志。
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
