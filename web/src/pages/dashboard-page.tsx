import clsx from "clsx";
import {
  Activity,
  CheckCircle2,
  Clock3,
  TriangleAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Card, StatusDot } from "@/components/ui/primitives";
import type { AdminLocale, DashboardStatKey, TaskStatus } from "@/data/admin-mocks";
import { useDashboardData } from "@/hooks/use-dashboard-data";
import {
  formatCompactNumber,
  formatTimestamp,
} from "@/lib/admin-format";

const statIcons: Record<DashboardStatKey, typeof Activity> = {
  activeTasks: Activity,
  queued: Clock3,
  completed: CheckCircle2,
  failed: TriangleAlert,
};

const statTones: Record<DashboardStatKey, "accent" | "warning" | "success" | "danger"> = {
  activeTasks: "accent",
  queued: "warning",
  completed: "success",
  failed: "danger",
};

const statusToneMap: Record<TaskStatus, "accent" | "warning" | "success" | "danger"> = {
  live: "accent",
  queued: "warning",
  completed: "success",
  failed: "danger",
};

const eyebrowClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableHeadClassName = "px-4 pb-2 text-left font-display text-[11px] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableCellClassName = "bg-surface-container-lowest px-4 py-3 align-top text-sm text-text-secondary first:rounded-l-lg last:rounded-r-lg";

export function DashboardPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en";
  const { data, loading, error } = useDashboardData();

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error || !data) return <div className="flex items-center justify-center h-full text-red-500">{error || "Failed to load"}</div>;

  const { stats, recentTasks } = data;

  return (
    <div className="grid gap-6">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {stats.map((item) => {
          const Icon = statIcons[item.key];

          return (
            <Card key={item.key} className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="grid gap-2">
                  <div className={eyebrowClassName}>{t(`dashboard.stats.${item.key}.label`)}</div>
                  <div className="text-3xl font-semibold tracking-[-0.04em] text-text-primary">
                    {formatCompactNumber(locale, item.value)}
                  </div>
                </div>
                <div className={clsx(
                  "flex h-11 w-11 items-center justify-center rounded-xl border",
                  {
                    "border-outline bg-surface-container-low text-accent-strong": statTones[item.key] === "accent",
                    "border-outline bg-surface-container-low text-warning-text": statTones[item.key] === "warning",
                    "border-outline bg-surface-container-low text-success-text": statTones[item.key] === "success",
                    "border-outline bg-surface-container-low text-danger-text": statTones[item.key] === "danger",
                  },
                )}
                >
                  <Icon className="h-5 w-5" />
                </div>
              </div>
            </Card>
          );
        })}
      </section>

      <section className="grid gap-4">
        <Card className="grid gap-5 p-5">
          <h2 className="text-lg font-semibold tracking-[-0.03em] text-text-primary">{t("dashboard.recentTasks.title")}</h2>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-separate border-spacing-y-2">
              <thead>
                <tr>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.task")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.model")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.status")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.created")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.owner")}</th>
                </tr>
              </thead>
              <tbody>
                {recentTasks.map((task) => (
                  <tr key={task.id}>
                    <td className={tableCellClassName}>
                      <div className="font-mono text-sm font-semibold text-text-primary">{task.id}</div>
                    </td>
                    <td className={tableCellClassName}>{task.model}</td>
                    <td className={tableCellClassName}>
                      <StatusDot tone={statusToneMap[task.status]} label={t(`common.status.${task.status}`)} />
                    </td>
                    <td className={tableCellClassName}>{formatTimestamp(locale, task.createdAt)}</td>
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
