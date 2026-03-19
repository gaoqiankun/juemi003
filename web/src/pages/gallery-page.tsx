import { CheckCircle2, Eye, Grid3X3, LoaderCircle, OctagonX } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useGen3d } from "@/app/gen3d-provider";
import { TaskSheet } from "@/components/task-sheet";
import { TaskThumbnail } from "@/components/task-thumbnail";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/format";
import type { GalleryFilter } from "@/lib/types";

const filters: Array<{ value: GalleryFilter; label: string; icon: typeof Grid3X3 }> = [
  { value: "all", label: "全部", icon: Grid3X3 },
  { value: "processing", label: "生成中", icon: LoaderCircle },
  { value: "completed", label: "已完成", icon: CheckCircle2 },
  { value: "failed", label: "失败", icon: OctagonX },
];

function getStatusDotClass(status?: string) {
  if (status === "succeeded") {
    return "bg-[#16a34a]";
  }
  if (status === "failed" || status === "cancelled") {
    return "bg-[#dc2626]";
  }
  return "bg-[#ca8a04]";
}

function isTerminal(status?: string) {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function GalleryPage({ initialSelectedTaskId = "" }: { initialSelectedTaskId?: string }) {
  const {
    taskMap,
    taskPage,
    galleryFilter,
    setGalleryFilter,
    getFilteredTasks,
    refreshTaskList,
    refreshTask,
    subscribeToTask,
    deleteTask,
  } = useGen3d();
  const [selectedTaskId, setSelectedTaskId] = useState(initialSelectedTaskId);
  const [confirmTaskId, setConfirmTaskId] = useState("");

  const filteredTasks = useMemo(() => getFilteredTasks(galleryFilter), [galleryFilter, getFilteredTasks]);
  const selectedTask = selectedTaskId ? taskMap[selectedTaskId] || null : null;
  const confirmTask = confirmTaskId ? taskMap[confirmTaskId] || null : null;

  useEffect(() => {
    if (initialSelectedTaskId) {
      setSelectedTaskId(initialSelectedTaskId);
    }
  }, [initialSelectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) {
      return;
    }
    refreshTask(selectedTaskId, { silent: true }).catch(() => undefined);
    if (selectedTask && !isTerminal(selectedTask.status)) {
      subscribeToTask(selectedTaskId, true).catch(() => undefined);
    }
  }, [refreshTask, selectedTask, selectedTaskId, subscribeToTask]);

  return (
    <section className="min-h-[calc(100vh-48px)] bg-[#000000]">
      <div className="px-6 pb-3 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          {filters.map((filter) => {
            const active = galleryFilter === filter.value;
            const Icon = filter.icon;
            return (
              <button
                key={filter.value}
                type="button"
                className={[
                  "inline-flex h-9 items-center gap-2 rounded-full border px-4 text-[13px] transition",
                  active
                    ? "border-white bg-white text-black"
                    : "border-[#2a2a2a] bg-transparent text-[#888888] hover:border-[#3a3a3a] hover:text-white",
                ].join(" ")}
                onClick={() => setGalleryFilter(filter.value)}
              >
                <Icon className="h-4 w-4" />
                {filter.label}
              </button>
            );
          })}
        </div>
      </div>

      {filteredTasks.length ? (
        <div
          className="grid gap-2 px-6 pb-6"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}
        >
          {filteredTasks.map((task) => (
            <article
              key={task.taskId}
              className="group relative cursor-pointer overflow-hidden rounded-[10px] bg-[#111111] transition-transform duration-150 ease-out hover:scale-[1.02]"
              style={{ aspectRatio: "1 / 1" }}
              onClick={() => setSelectedTaskId(task.taskId)}
            >
              <TaskThumbnail task={task} variant="gallery" className="!aspect-auto size-full rounded-[10px] bg-[#111111]" />

              <div className="absolute inset-0 flex items-center justify-center bg-[rgba(0,0,0,0.4)] opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                <button
                  type="button"
                  className="inline-flex h-10 items-center justify-center rounded-full bg-white px-5 text-[13px] font-medium text-black transition hover:bg-[#f3f3f3]"
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelectedTaskId(task.taskId);
                  }}
                >
                  <Eye className="mr-2 h-4 w-4" />
                  查看
                </button>
              </div>

              <div className="absolute inset-x-0 bottom-0 bg-[linear-gradient(180deg,rgba(0,0,0,0),rgba(0,0,0,0.8))] px-[10px] pb-2 pt-5">
                <div className="flex items-end justify-between">
                  <div className="text-[11px] text-[#aaaaaa]">{formatRelativeTime(task.createdAt)}</div>
                  <span className={`h-2 w-2 rounded-full ${getStatusDotClass(task.status)}`} />
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="px-6 pb-6">
          <div className="flex min-h-[320px] items-center justify-center rounded-[10px] bg-[#111111] text-[13px] text-[#444444]">
            暂无内容
          </div>
        </div>
      )}

      {taskPage.hasMore ? (
        <div className="flex justify-center px-6 pb-8">
          <Button
            variant="outline"
            className="h-10 rounded-[8px] border-[#2a2a2a] bg-[#111111] px-4 text-white hover:bg-[#1a1a1a]"
            disabled={taskPage.isLoading}
            onClick={() => refreshTaskList({ append: true, resubscribe: false, silent: false }).catch(() => undefined)}
          >
            {taskPage.isLoading ? "加载中…" : "加载更多"}
          </Button>
        </div>
      ) : null}

      <TaskSheet
        task={selectedTask}
        open={Boolean(selectedTask)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedTaskId("");
          }
        }}
        onDeleteRequest={(taskId) => setConfirmTaskId(taskId)}
      />

      <AlertDialog
        open={Boolean(confirmTask)}
        onOpenChange={(open) => {
          if (!open) {
            setConfirmTaskId("");
          }
        }}
      >
        <AlertDialogContent className="border-[#1f1f1f] bg-[#111111]">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">删除这条记录？</AlertDialogTitle>
            <AlertDialogDescription className="text-[#888888]">
              删除后，这条记录会从图库中移除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button variant="outline" className="border-[#333333] bg-transparent text-white hover:bg-[#1a1a1a]">
                取消
              </Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                className="bg-white text-black shadow-none hover:bg-[#eeeeee]"
                onClick={() => {
                  const deletingTaskId = confirmTaskId;
                  deleteTask(deletingTaskId)
                    .then(() => {
                      if (selectedTaskId === deletingTaskId) {
                        setSelectedTaskId("");
                      }
                      setConfirmTaskId("");
                    })
                    .catch(() => undefined);
                }}
              >
                删除
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
