import { Eye, Plus } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useGen3d } from "@/app/gen3d-provider";
import { TaskThumbnail } from "@/components/task-thumbnail";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/format";
import type { GalleryFilter } from "@/lib/types";

const filters: Array<{ value: GalleryFilter; labelKey: string }> = [
  { value: "all", labelKey: "user.gallery.filters.all" },
  { value: "processing", labelKey: "user.gallery.filters.processing" },
  { value: "completed", labelKey: "user.gallery.filters.completed" },
  { value: "failed", labelKey: "user.gallery.filters.failed" },
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

export function GalleryPage({ initialSelectedTaskId: _initialSelectedTaskId = "" }: { initialSelectedTaskId?: string } = {}) {
  const { t, i18n } = useTranslation();
  const {
    taskPage,
    galleryFilter,
    setGalleryFilter,
    getFilteredTasks,
    refreshTaskList,
  } = useGen3d();

  const filteredTasks = useMemo(() => getFilteredTasks(galleryFilter), [galleryFilter, getFilteredTasks]);

  return (
    <section className="pb-20">
      <div className="mx-auto grid w-full max-w-7xl gap-4">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-[-0.03em] text-text-primary">
              {t("user.gallery.title")}
            </h1>
          </div>

          <div className="overflow-x-auto pb-1 md:pb-0">
            <div className="inline-flex min-w-max items-center rounded-xl bg-surface-container-low p-1">
              {filters.map((filter) => {
                const active = galleryFilter === filter.value;
                return (
                  <button
                    key={filter.value}
                    type="button"
                    className={[
                      "inline-flex h-9 items-center rounded-lg px-4 text-xs font-semibold transition-colors duration-200",
                      active
                        ? "bg-surface-container-highest text-accent-strong shadow-soft"
                        : "text-text-secondary hover:text-text-primary",
                    ].join(" ")}
                    onClick={() => setGalleryFilter(filter.value)}
                  >
                    {t(filter.labelKey)}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {filteredTasks.length ? (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}
          >
            {filteredTasks.map((task) => (
              <Link
                key={task.taskId}
                to={`/viewer/${task.taskId}`}
                className="group relative overflow-hidden rounded-[24px] border border-outline bg-surface-container-lowest transition-all duration-200 ease-out hover:-translate-y-1 hover:shadow-float"
                style={{ aspectRatio: "1 / 1" }}
              >
                <TaskThumbnail task={task} variant="gallery" className="!aspect-auto size-full rounded-[24px] bg-surface-container-lowest" />

                <div className="absolute inset-0 flex items-center justify-center bg-[color:color-mix(in_srgb,var(--surface-container-lowest)_42%,transparent)] opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                  <span className="inline-flex h-11 items-center justify-center rounded-full border border-outline bg-surface px-5 text-sm font-medium text-text-primary shadow-float transition hover:bg-surface-container-high">
                    <Eye className="mr-2 h-4 w-4" />
                    {t("user.gallery.view")}
                  </span>
                </div>

                <div className="absolute inset-x-0 bottom-0 bg-[linear-gradient(180deg,transparent,color-mix(in_srgb,var(--surface-container-lowest)_92%,transparent))] px-4 pb-4 pt-10">
                  <div className="flex items-end justify-between gap-3">
                    <div className="text-xs font-medium text-text-secondary">{formatRelativeTime(task.createdAt, i18n.resolvedLanguage)}</div>
                    <span
                      className={`h-2.5 w-2.5 rounded-full ring-4 ring-[color:color-mix(in_srgb,var(--surface-container-lowest)_78%,transparent)] ${getStatusDotClass(task.status)}`}
                    />
                  </div>
                </div>
              </Link>
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
      </div>

      <Button
        asChild
        size="icon"
        className="fixed bottom-8 right-8 z-40 h-14 w-14 rounded-full border-0 bg-accent text-accent-ink shadow-float transition-transform duration-200 hover:scale-105 hover:bg-accent-strong"
      >
        <Link
          to="/generate"
          aria-label={t("user.gallery.create")}
          title={t("user.gallery.create")}
        >
          <Plus className="h-6 w-6" />
        </Link>
      </Button>
    </section>
  );
}
