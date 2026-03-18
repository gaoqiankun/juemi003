import { useEffect, useMemo, useState } from "react";
import { Eye, GalleryHorizontalEnd, RefreshCcw, Trash2 } from "lucide-react";

import { useGen3d } from "@/app/gen3d-provider";
import { TaskSheet } from "@/components/task-sheet";
import { TaskStatusBadge } from "@/components/task-status-badge";
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatRelativeTime, formatTime, getTaskShortId } from "@/lib/format";
import type { GalleryFilter } from "@/lib/types";

const filters: Array<{ value: GalleryFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "processing", label: "处理中" },
  { value: "completed", label: "完成" },
  { value: "failed", label: "失败" },
];

export function GalleryPage() {
  const {
    tasks,
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
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [confirmTaskId, setConfirmTaskId] = useState("");

  const filteredTasks = useMemo(() => getFilteredTasks(galleryFilter), [galleryFilter, getFilteredTasks]);
  const selectedTask = selectedTaskId ? taskMap[selectedTaskId] || null : null;
  const confirmTask = confirmTaskId ? taskMap[confirmTaskId] || null : null;

  useEffect(() => {
    if (!selectedTaskId) {
      return;
    }
    refreshTask(selectedTaskId, { silent: true }).catch(() => undefined);
    if (selectedTask && selectedTask.status !== "succeeded" && selectedTask.status !== "failed" && selectedTask.status !== "cancelled") {
      subscribeToTask(selectedTaskId, true).catch(() => undefined);
    }
  }, [refreshTask, selectedTask?.status, selectedTaskId, subscribeToTask]);

  return (
    <section className="space-y-6">
      <Card className="bg-[linear-gradient(160deg,rgba(10,18,34,0.98),rgba(7,11,22,0.94))]">
        <CardHeader className="md:flex-row md:items-end md:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.26em] text-slate-500">Gallery</div>
            <CardTitle className="mt-3 text-4xl md:text-5xl">历史任务工作台。</CardTitle>
            <CardDescription className="mt-4 max-w-3xl text-base text-slate-300">
              用卡片网格统一浏览历史生成记录，完成态任务支持直接预览和下载，处理中任务可以继续追踪进度。
            </CardDescription>
          </div>
          <Button variant="outline" onClick={() => refreshTaskList({ append: false, resubscribe: true, silent: false }).catch(() => undefined)}>
            <RefreshCcw className="h-4 w-4" />
            刷新图库
          </Button>
        </CardHeader>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <Tabs value={galleryFilter} onValueChange={(value) => setGalleryFilter(value as GalleryFilter)}>
          <TabsList>
            {filters.map((filter) => (
              <TabsTrigger key={filter.value} value={filter.value}>
                {filter.label} · {getFilteredTasks(filter.value).length}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="text-sm text-slate-400">共 {tasks.length} 条任务记录</div>
      </div>

      {filteredTasks.length ? (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {filteredTasks.map((task) => (
            <button
              key={task.taskId}
              type="button"
              onClick={() => setSelectedTaskId(task.taskId)}
              className="group text-left"
            >
              <Card className="h-full overflow-hidden transition duration-200 hover:-translate-y-1 hover:border-cyan-400/20 hover:bg-white/[0.08]">
                <CardContent className="space-y-4 p-4">
                  <TaskThumbnail task={task} compact />
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-display text-xl font-semibold text-white">{getTaskShortId(task.taskId)}</div>
                      <div className="mt-1 text-sm text-slate-400">{formatTime(task.createdAt)} · {formatRelativeTime(task.createdAt)}</div>
                    </div>
                    <TaskStatusBadge task={task} />
                  </div>
                  <div className="flex items-center justify-between gap-3 rounded-[22px] border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">
                    <span className="inline-flex items-center gap-2">
                      <Eye className="h-4 w-4 text-cyan-200" />
                      查看详情
                    </span>
                    <span className="text-xs uppercase tracking-[0.18em] text-slate-500">{task.model}</span>
                  </div>
                </CardContent>
              </Card>
            </button>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex min-h-[280px] flex-col items-center justify-center gap-4 text-center">
            <GalleryHorizontalEnd className="h-12 w-12 text-slate-400" />
            <div>
              <div className="font-display text-2xl font-semibold text-white">当前筛选下暂无任务</div>
              <div className="mt-3 max-w-md text-sm leading-7 text-slate-400">创建新任务后，历史记录会自动汇总到这里，支持分页加载与详情预览。</div>
            </div>
          </CardContent>
        </Card>
      )}

      {taskPage.hasMore ? (
        <div className="flex justify-center">
          <Button variant="outline" disabled={taskPage.isLoading} onClick={() => refreshTaskList({ append: true, resubscribe: false, silent: false }).catch(() => undefined)}>
            {taskPage.isLoading ? "加载中…" : "加载更多任务"}
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

      <AlertDialog open={Boolean(confirmTask)} onOpenChange={(open) => {
        if (!open) {
          setConfirmTaskId("");
        }
      }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除当前任务？</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmTask ? `任务 ${getTaskShortId(confirmTask.taskId)} 将从图库实时移除，并触发后端 artifact 清理。` : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button variant="outline" onClick={() => setConfirmTaskId("")}>取消</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                variant="destructive"
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
                <Trash2 className="h-4 w-4" />
                删除任务
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
