import type { ReactNode } from "react";
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

import type { AdminLocale, DashboardStatKey, NodeStatus, TaskStatus } from "@/data/admin-mocks";
import { Card, MeterBar, StatusDot } from "@/components/ui/primitives";
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

export function DashboardPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en";
  const { stats, gpu, recentTasks, nodes } = useDashboardData();

  return (
    <div className="page-stack">
      <section className="page-header">
        <div>
          <div className="eyebrow">{t("shell.nav.dashboard")}</div>
          <h2 className="page-title">{t("dashboard.title")}</h2>
        </div>
        <p className="page-description">{t("dashboard.description")}</p>
      </section>

      <section className="stats-grid">
        {stats.map((item) => {
          const Icon = statIcons[item.key];
          return (
            <Card key={item.key}>
              <div className="card-header-row">
                <div>
                  <div className="eyebrow">{t(`dashboard.stats.${item.key}.label`)}</div>
                  <div className="metric-value">{formatCompactNumber(locale, item.value)}</div>
                </div>
                <div className={`metric-icon metric-icon-${statTones[item.key]}`}>
                  <Icon className="metric-icon-svg" />
                </div>
              </div>
              <div className="metric-foot">
                <span className="metric-delta">{item.change}</span>
                <span className="metric-copy">{t(`dashboard.stats.${item.key}.helper`)}</span>
              </div>
            </Card>
          );
        })}
      </section>

      <section className="dashboard-grid">
        <Card className="gpu-card">
          <div className="section-header">
            <div>
              <div className="eyebrow">{t("dashboard.gpu.title")}</div>
              <h3 className="section-title">{gpu.model}</h3>
            </div>
            <Cpu className="section-icon" />
          </div>
          <p className="section-description">{t("dashboard.gpu.subtitle")}</p>

          <div className="gpu-meter-block">
            <div className="meter-meta">
              <span>{t("dashboard.gpu.utilization")}</span>
              <span className="numeric">{formatPercent(locale, gpu.utilization)}</span>
            </div>
            <MeterBar value={gpu.utilization} />
          </div>

          <div className="gpu-meter-block">
            <div className="meter-meta">
              <span>{t("dashboard.gpu.vram")}</span>
              <span className="numeric">
                {formatNumber(locale, gpu.vramUsedGb, 1)} / {formatNumber(locale, gpu.vramTotalGb, 0)} GB
              </span>
            </div>
            <MeterBar value={gpu.vramUsedGb} max={gpu.vramTotalGb} />
          </div>

          <div className="detail-grid detail-grid-two">
            <DetailItem
              icon={<Flame className="detail-icon" />}
              label={t("dashboard.gpu.temperature")}
              value={`${formatNumber(locale, gpu.temperatureC)}°C`}
            />
            <DetailItem
              icon={<Zap className="detail-icon" />}
              label={t("dashboard.gpu.power")}
              value={`${formatNumber(locale, gpu.powerW)}W`}
            />
            <DetailItem
              icon={<Gauge className="detail-icon" />}
              label={t("dashboard.gpu.fans")}
              value={formatPercent(locale, gpu.fanPercent)}
            />
            <DetailItem
              icon={<Cpu className="detail-icon" />}
              label={t("dashboard.gpu.cuda")}
              value={gpu.cudaVersion}
            />
            <DetailItem
              icon={<ServerCog className="detail-icon" />}
              label={t("dashboard.gpu.driver")}
              value={gpu.driverVersion}
            />
            <DetailItem
              icon={<Activity className="detail-icon" />}
              label={t("dashboard.gpu.activeJobs")}
              value={formatNumber(locale, gpu.activeJobs)}
            />
          </div>

          <div className="gpu-summary-strip">
            <div>
              <div className="eyebrow">{t("dashboard.gpu.avgLatency")}</div>
              <div className="summary-value">{formatNumber(locale, gpu.avgLatencySeconds)}s</div>
            </div>
            <div className="summary-chip">{formatPercent(locale, gpu.utilization)} busy</div>
          </div>
        </Card>

        <Card>
          <div className="section-header">
            <div>
              <div className="eyebrow">{t("dashboard.recentTasks.title")}</div>
              <h3 className="section-title">{t("dashboard.recentTasks.subtitle")}</h3>
            </div>
          </div>

          <div className="table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>{t("dashboard.recentTasks.columns.task")}</th>
                  <th>{t("dashboard.recentTasks.columns.model")}</th>
                  <th>{t("dashboard.recentTasks.columns.status")}</th>
                  <th>{t("dashboard.recentTasks.columns.duration")}</th>
                  <th>{t("dashboard.recentTasks.columns.created")}</th>
                  <th>{t("dashboard.recentTasks.columns.owner")}</th>
                </tr>
              </thead>
              <tbody>
                {recentTasks.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <div className="table-primary mono">{task.id}</div>
                      <div className="table-secondary">{t(`common.${task.subjectKey}`)}</div>
                    </td>
                    <td>{task.model}</td>
                    <td>
                      <StatusDot
                        tone={statusToneMap[task.status]}
                        label={t(`common.status.${task.status}`)}
                      />
                    </td>
                    <td className="numeric">{formatNumber(locale, task.durationSeconds)}s</td>
                    <td>{formatTimestamp(locale, task.createdAt)}</td>
                    <td>{task.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>

      <section>
        <div className="section-header">
          <div>
            <div className="eyebrow">{t("dashboard.nodes.title")}</div>
            <h3 className="section-title">{t("dashboard.nodes.subtitle")}</h3>
          </div>
        </div>

        <div className="node-grid">
          {nodes.map((node) => (
            <Card key={node.id} tone="muted">
              <div className="card-header-row">
                <div>
                  <div className="table-primary mono">{node.id}</div>
                  <div className="table-secondary">{node.gpu}</div>
                </div>
                <StatusDot
                  tone={nodeStatusTones[node.status]}
                  label={t(`common.status.${node.status}`)}
                />
              </div>
              <div className="detail-grid">
                <DetailItem label={t("dashboard.nodes.zone")} value={node.zone} />
                <DetailItem label={t("dashboard.nodes.pending")} value={formatNumber(locale, node.pendingTasks)} />
                <DetailItem label={t("dashboard.nodes.uptime")} value={`${formatNumber(locale, node.uptimeHours)}h`} />
                <DetailItem
                  label={t("dashboard.nodes.throughput")}
                  value={`${formatNumber(locale, node.throughputPerHour, 1)}/h`}
                />
              </div>
              <div className="gpu-meter-block">
                <div className="meter-meta">
                  <span>{t("dashboard.gpu.utilization")}</span>
                  <span className="numeric">{formatPercent(locale, node.utilization)}</span>
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
    <div className="detail-item">
      <div className="detail-label">
        {icon}
        <span>{label}</span>
      </div>
      <div className="detail-value">{value}</div>
    </div>
  );
}
