import type { ReactNode } from "react";
import clsx from "clsx";
import {
  Activity,
  CheckCircle2,
  Clock3,
  Cpu,
  Flame,
  Gauge,
  ServerCog,
  TriangleAlert,
  Zap,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Card, MeterBar, StatusDot } from "@/components/ui/primitives";
import type { AdminLocale, DashboardStatKey, NodeStatus, TaskStatus } from "@/data/admin-mocks";
import { useDashboardData } from "@/hooks/use-dashboard-data";
import {
  formatCompactNumber,
  formatNumber,
  formatPercent,
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

const nodeStatusTones: Record<NodeStatus, "success" | "warning" | "danger"> = {
  online: "success",
  warning: "warning",
  offline: "danger",
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

  const { stats, gpu, recentTasks, nodes } = data;

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className={eyebrowClassName}>{t("shell.nav.dashboard")}</div>
          <h2 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-text-primary">{t("dashboard.title")}</h2>
        </div>
      </section>

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

              <div className="mt-5 flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold text-accent-strong">{item.change}</span>
                <span className="text-text-secondary">{t(`dashboard.stats.${item.key}.helper`)}</span>
              </div>
            </Card>
          );
        })}
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.02fr)_minmax(0,0.98fr)]">
        <Card className="grid gap-6 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className={eyebrowClassName}>{t("dashboard.gpu.title")}</div>
              <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">{gpu.model}</h3>
            </div>
            <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-outline bg-surface-container-low text-accent-strong">
              <Cpu className="h-5 w-5" />
            </div>
          </div>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-4 text-sm text-text-secondary">
                <span>{t("dashboard.gpu.utilization")}</span>
                <span className="font-mono text-text-primary">{formatPercent(locale, gpu.utilization)}</span>
              </div>
              <MeterBar value={gpu.utilization} />
            </div>

            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-4 text-sm text-text-secondary">
                <span>{t("dashboard.gpu.vram")}</span>
                <span className="font-mono text-text-primary">
                  {formatNumber(locale, gpu.vramUsedGb, 1)} / {formatNumber(locale, gpu.vramTotalGb, 0)} GB
                </span>
              </div>
              <MeterBar value={gpu.vramUsedGb} max={gpu.vramTotalGb} />
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <DetailItem
              icon={<Flame className="h-4 w-4 text-warning-text" />}
              label={t("dashboard.gpu.temperature")}
              value={`${formatNumber(locale, gpu.temperatureC)}°C`}
            />
            <DetailItem
              icon={<Zap className="h-4 w-4 text-accent-strong" />}
              label={t("dashboard.gpu.power")}
              value={`${formatNumber(locale, gpu.powerW)}W`}
            />
            <DetailItem
              icon={<Gauge className="h-4 w-4 text-accent-strong" />}
              label={t("dashboard.gpu.fans")}
              value={formatPercent(locale, gpu.fanPercent)}
            />
            <DetailItem
              icon={<Cpu className="h-4 w-4 text-accent-strong" />}
              label={t("dashboard.gpu.cuda")}
              value={gpu.cudaVersion}
            />
            <DetailItem
              icon={<ServerCog className="h-4 w-4 text-accent-strong" />}
              label={t("dashboard.gpu.driver")}
              value={gpu.driverVersion}
            />
            <DetailItem
              icon={<Activity className="h-4 w-4 text-success-text" />}
              label={t("dashboard.gpu.activeJobs")}
              value={formatNumber(locale, gpu.activeJobs)}
            />
          </div>

          <div className="flex flex-col gap-3 rounded-xl border border-outline bg-surface-container-low px-4 py-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className={eyebrowClassName}>{t("dashboard.gpu.avgLatency")}</div>
              <div className="mt-1 text-xl font-semibold tracking-[-0.03em] text-text-primary">
                {formatNumber(locale, gpu.avgLatencySeconds)}s
              </div>
            </div>
            <div className="inline-flex items-center rounded-full border border-outline bg-surface-container-highest px-3 py-1.5 text-sm font-medium text-text-secondary">
              {t("dashboard.gpu.busyChip", { value: formatPercent(locale, gpu.utilization) })}
            </div>
          </div>
        </Card>

        <Card className="grid gap-5 p-5">
          <div>
            <div className={eyebrowClassName}>{t("dashboard.recentTasks.title")}</div>
            <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">
              {t("dashboard.recentTasks.subtitle")}
            </h3>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-separate border-spacing-y-2">
              <thead>
                <tr>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.task")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.model")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.status")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.duration")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.created")}</th>
                  <th className={tableHeadClassName}>{t("dashboard.recentTasks.columns.owner")}</th>
                </tr>
              </thead>
              <tbody>
                {recentTasks.map((task) => (
                  <tr key={task.id}>
                    <td className={tableCellClassName}>
                      <div className="font-mono text-sm font-semibold text-text-primary">{task.id}</div>
                      <div className="mt-1 text-sm text-text-secondary">{t(`common.${task.subjectKey}`)}</div>
                    </td>
                    <td className={tableCellClassName}>{task.model}</td>
                    <td className={tableCellClassName}>
                      <StatusDot tone={statusToneMap[task.status]} label={t(`common.status.${task.status}`)} />
                    </td>
                    <td className={`${tableCellClassName} font-mono`}>{formatNumber(locale, task.durationSeconds)}s</td>
                    <td className={tableCellClassName}>{formatTimestamp(locale, task.createdAt)}</td>
                    <td className={tableCellClassName}>{task.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>

      <section className="grid gap-4">
        <div>
          <div className={eyebrowClassName}>{t("dashboard.nodes.title")}</div>
          <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">
            {t("dashboard.nodes.subtitle")}
          </h3>
        </div>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {nodes.map((node) => (
            <Card key={node.id} tone="low" className="grid gap-5 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="font-mono text-sm font-semibold text-text-primary">{node.id}</div>
                  <div className="mt-1 text-sm text-text-secondary">{node.gpu}</div>
                </div>
                <StatusDot tone={nodeStatusTones[node.status]} label={t(`common.status.${node.status}`)} />
              </div>

              <div className="grid gap-3">
                <DetailItem label={t("dashboard.nodes.zone")} value={node.zone} />
                <DetailItem label={t("dashboard.nodes.pending")} value={formatNumber(locale, node.pendingTasks)} />
                <DetailItem label={t("dashboard.nodes.uptime")} value={`${formatNumber(locale, node.uptimeHours)}h`} />
                <DetailItem
                  label={t("dashboard.nodes.throughput")}
                  value={`${formatNumber(locale, node.throughputPerHour, 1)}/h`}
                />
              </div>

              <div className="grid gap-2">
                <div className="flex items-center justify-between gap-4 text-sm text-text-secondary">
                  <span>{t("dashboard.gpu.utilization")}</span>
                  <span className="font-mono text-text-primary">{formatPercent(locale, node.utilization)}</span>
                </div>
                <MeterBar value={node.utilization} />
              </div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}

function DetailItem({
  icon,
  label,
  value,
}: {
  icon?: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="grid gap-2 rounded-xl border border-outline bg-surface-container-low p-4">
      <div className="flex items-center gap-2 text-sm text-text-muted">
        {icon}
        <span>{label}</span>
      </div>
      <div className="text-sm font-semibold text-text-primary">{value}</div>
    </div>
  );
}
