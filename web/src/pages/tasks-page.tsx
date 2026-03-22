import { useDeferredValue, useState } from "react";
import { Search, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Card, StatusDot, Tabs, TabsList, TabsTrigger, TextField } from "@/components/ui/primitives";
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
  const { data, loading, error } = useTasksData();
  const [filter, setFilter] = useState<TaskStatus | "all">("all");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(String(search || "").trim().toLowerCase());

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error || !data) return <div className="flex items-center justify-center h-full text-red-500">{error || "Failed to load"}</div>;

  const { overview, tasks } = data;

  const filteredTasks = tasks.filter((task) => {
    if (filter !== "all" && task.status !== filter) {
      return false;
    }

    if (!deferredSearch) {
      return true;
    }

    return [
      task.id.toLowerCase(),
      task.owner.toLowerCase(),
      task.model.toLowerCase(),
    ].some((value) => value.includes(deferredSearch));
  });

  return (
    <div className="grid gap-6">
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
          </Card>
        ))}
      </section>

      <section className="grid gap-4">
        <Card className="grid gap-5 p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
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
                  <th className={tableHeadClassName}>{t("tasks.table.columns.model")}</th>
                  <th className={tableHeadClassName}>{t("tasks.table.columns.status")}</th>
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
                    </td>
                    <td className={tableCellClassName}>{task.model}</td>
                    <td className={tableCellClassName}>
                      <StatusDot tone={statusToneMap[task.status]} label={t(`common.status.${task.status}`)} />
                    </td>
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
      </section>
    </div>
  );
}
