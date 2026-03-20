import { CheckCircle2, Eye, Grid3X3, LoaderCircle, OctagonX } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

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

const filters: Array<{ value: GalleryFilter; labelKey: string; icon: typeof Grid3X3 }> = [
  { value: "all", labelKey: "user.gallery.filters.all", icon: Grid3X3 },
  { value: "processing", labelKey: "user.gallery.filters.processing", icon: LoaderCircle },
  { value: "completed", labelKey: "user.gallery.filters.completed", icon: CheckCircle2 },
  { value: "failed", labelKey: "user.gallery.filters.failed", icon: OctagonX },
];

function getStatusDotClass(status?: string) {
  if (status === "succeeded") {
    return "bg-success-text";
  }
  if (status === "failed" || status === "cancelled") {
    return "bg-danger-text";
  }
  return "bg-warning-text";
}

function isTerminal(status?: string) {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function GalleryPage({ initialSelectedTaskId = "" }: { initialSelectedTaskId?: string }) {
  const { t } = useTranslation();
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
    <section className="grid gap-4">
      <div className="overflow-x-auto pb-1">
        <div className="flex min-w-max items-center gap-2 rounded-[24px] border border-outline bg-surface-glass p-2 shadow-float backdrop-blur-xl">
          {filters.map((filter) => {
            const active = galleryFilter === filter.value;
            const Icon = filter.icon;
            return (
              <button
                key={filter.value}
                type="button"
                className={[
                  "inline-flex h-10 items-center gap-2 rounded-full border px-4 text-sm font-medium tracking-[-0.02em] transition-all duration-200",
                  active
                    ? "border-[color:color-mix(in_srgb,var(--accent)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_14%,var(--surface-container-highest))] text-accent-strong shadow-float"
                    : "border-transparent bg-transparent text-text-secondary hover:border-outline hover:bg-surface-container-low hover:text-text-primary",
                ].join(" ")}
                onClick={() => setGalleryFilter(filter.value)}
              >
                <Icon className="h-4 w-4" />
                {t(filter.labelKey)}
              </button>
            );
          })}
        </div>
      </div>

      {filteredTasks.length ? (
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}
        >
          {filteredTasks.map((task) => (
            <article
              key={task.taskId}
              className="group relative cursor-pointer overflow-hidden rounded-[24px] border border-outline bg-surface-container-lowest transition-all duration-200 ease-out hover:-translate-y-1 hover:shadow-float"
              style={{ aspectRatio: "1 / 1" }}
              onClick={() => setSelectedTaskId(task.taskId)}
            >
              <TaskThumbnail task={task} variant="gallery" className="!aspect-auto size-full rounded-[24px] bg-surface-container-lowest" />

              <div className="absolute inset-0 flex items-center justify-center bg-[color:color-mix(in_srgb,var(--surface-container-lowest)_42%,transparent)] opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                <button
                  type="button"
                  className="inline-flex h-11 items-center justify-center rounded-full border border-outline bg-surface px-5 text-sm font-medium text-text-primary shadow-float transition hover:bg-surface-container-high"
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelectedTaskId(task.taskId);
                  }}
                >
                  <Eye className="mr-2 h-4 w-4" />
                  {t("user.gallery.view")}
                </button>
              </div>

              <div className="absolute inset-x-0 bottom-0 bg-[linear-gradient(180deg,transparent,color-mix(in_srgb,var(--surface-container-lowest)_92%,transparent))] px-4 pb-4 pt-10">
                <div className="flex items-end justify-between gap-3">
                  <div className="text-xs font-medium text-text-secondary">{formatRelativeTime(task.createdAt)}</div>
                  <span
                    className={`h-2.5 w-2.5 rounded-full ring-4 ring-[color:color-mix(in_srgb,var(--surface-container-lowest)_78%,transparent)] ${getStatusDotClass(task.status)}`}
                  />
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="flex min-h-[320px] items-center justify-center rounded-[24px] border border-dashed border-outline bg-[image:var(--page-gradient)] bg-surface-container-low px-6 text-sm text-text-secondary">
          {t("user.gallery.empty")}
        </div>
      )}

      {taskPage.hasMore ? (
        <div className="flex justify-center pt-1">
          <Button
            variant="outline"
            className="h-11 rounded-xl bg-surface-container-lowest px-5 shadow-soft hover:border-[color:color-mix(in_srgb,var(--accent)_26%,transparent)] hover:bg-surface-container-low hover:text-accent-strong"
            disabled={taskPage.isLoading}
            onClick={() => refreshTaskList({ append: true, resubscribe: false, silent: false }).catch(() => undefined)}
          >
            {taskPage.isLoading ? t("user.gallery.loadingMore") : t("user.gallery.loadMore")}
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
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("user.gallery.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("user.gallery.deleteDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button variant="outline">
                {t("user.gallery.cancel")}
              </Button>
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
                {t("user.gallery.delete")}
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
