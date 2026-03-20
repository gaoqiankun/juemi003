import { useDeferredValue, useState } from "react";
import { Search, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Card, MeterBar, StatusDot, Tabs, TabsList, TabsTrigger, TextField } from "@/components/ui/primitives";
import type { AdminLocale, TaskStatus } from "@/data/admin-mocks";
import { useTasksData } from "@/hooks/use-tasks-data";
import {
  formatNumber,
  formatTimestamp,
} from "@/lib/admin-format";

const statusToneMap: Record<TaskStatus, "accent" | "warning" | "success" | "danger"> = {
  live: "accent",
  queued: "warning",
  completed: "success",
  failed: "danger",
};

const filterValues: Array<TaskStatus | "all"> = ["all", "live", "queued", "completed", "failed"];
const eyebrowClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableHeadClassName = "px-4 pb-2 text-left font-display text-[11px] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableCellClassName = "bg-surface-container-lowest px-4 py-3 align-top text-sm text-text-secondary first:rounded-l-lg last:rounded-r-lg";

export function TasksPage() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en") as AdminLocale;
  const { overview, tasks, logs } = useTasksData();
  const [filter, setFilter] = useState<TaskStatus | "all">("all");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim().toLowerCase());

  const filteredTasks = tasks.filter((task) => {
    if (filter !== "all" && task.status !== filter) {
      return false;
    }

    if (!deferredSearch) {
      return true;
    }

    const subject = t(`common.${task.subjectKey}`).toLowerCase();
    return [
      task.id.toLowerCase(),
      task.owner.toLowerCase(),
      task.model.toLowerCase(),
      subject,
      task.queue.toLowerCase(),
    ].some((value) => value.includes(deferredSearch));
  });

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className={eyebrowClassName}>{t("shell.nav.tasks")}</div>
          <h2 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-text-primary">{t("tasks.title")}</h2>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {overview.map((item) => (
          <Card key={item.key} className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="grid gap-2">
                <div className={eyebrowClassName}>{t(`tasks.overview.${item.key}`)}</div>
                <div className="flex items-end gap-2">
                  <span className="text-3xl font-semibold tracking-[-0.04em] text-text-primary">
                    {formatNumber(locale, item.value, item.key === "throughput" ? 1 : 0)}
                  </span>
                  {item.unit ? <span className="pb-1 text-sm text-text-secondary">{item.unit}</span> : null}
                </div>
              </div>
              <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-outline bg-surface-container-low text-accent-strong">
                <Workflow className="h-5 w-5" />
              </div>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold text-accent-strong">{item.change}</span>
              <span className="text-text-secondary">{t("tasks.table.subtitle")}</span>
            </div>
          </Card>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_22rem]">
        <Card className="grid gap-5 p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <div className={eyebrowClassName}>{t("tasks.table.title")}</div>
              <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">
                {t("tasks.table.subtitle")}
              </h3>
            </div>

            <div className="relative w-full max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
              <TextField
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("tasks.searchPlaceholder")}
                className="pl-10"
              />
            </div>
          </div>

          <Tabs value={filter} onValueChange={(value) => setFilter(value as TaskStatus | "all")}>
            <TabsList>
              {filterValues.map((value) => (
                <TabsTrigger key={value} value={value}>
                  {t(`tasks.filters.${value}`)}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] border-separate border-spacing-y-2">
              <thead>
                <tr>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.task")}</th>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.subject")}</th>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.queue")}</th>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.progress")}</th>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.model")}</th>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.created")}</th>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.latency")}</th>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.owner")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.map((task) => (
                  <tr key={task.id}>
                    <td className={tableCellClassName}>
                      <div className="font-mono text-sm font-semibold text-text-primary">{task.id}</div>
                      <div className="mt-2">
                        <StatusDot tone={statusToneMap[task.status]} label={t(`common.status.${task.status}`)} />
                      </div>
                    </td>
                    <td className={tableCellClassName}>{t(`common.${task.subjectKey}`)}</td>
                    <td className={tableCellClassName}>{task.queue}</td>
                    <td className={tableCellClassName}>
                      <div className="grid gap-2">
                        <MeterBar value={task.progress} />
                        <span className="font-mono text-xs text-text-muted">{task.progress}%</span>
                      </div>
                    </td>
                    <td className={tableCellClassName}>{task.model}</td>
                    <td className={tableCellClassName}>{formatTimestamp(locale, task.createdAt)}</td>
                    <td className={`${tableCellClassName} font-mono`}>
                      {task.latencySeconds ? `${formatNumber(locale, task.latencySeconds)}s` : "—"}
                    </td>
                    <td className={tableCellClassName}>{task.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card tone="low" className="grid content-start gap-4 p-5">
          <div>
            <div className={eyebrowClassName}>{t("tasks.logs.title")}</div>
            <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">
              {t("tasks.logs.subtitle")}
            </h3>
          </div>

          <div className="grid gap-3">
            {logs.map((log) => (
              <div
                key={`${log.timestamp}-${log.messageKey}`}
                className="grid grid-cols-[auto_auto_1fr] items-center gap-3 rounded-xl border border-outline bg-surface-container px-4 py-3"
              >
                <span className="inline-flex min-w-[3.25rem] justify-center rounded-full border border-outline bg-surface-container-highest px-2.5 py-1 text-xs font-medium uppercase tracking-[0.04em] text-text-secondary">
                  {log.level}
                </span>
                <span className="font-mono text-xs text-text-muted">{log.timestamp}</span>
                <span className="text-sm leading-6 text-text-secondary">{t(log.messageKey)}</span>
              </div>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}
