import { useDeferredValue, useState } from "react";
import { Search, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AdminLocale, TaskStatus } from "@/data/admin-mocks";
import { Card, MeterBar, StatusDot, TextField } from "@/components/ui/primitives";
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
    <div className="page-stack">
      <section className="page-header">
        <div>
          <div className="eyebrow">{t("shell.nav.tasks")}</div>
          <h2 className="page-title">{t("tasks.title")}</h2>
        </div>
        <p className="page-description">{t("tasks.description")}</p>
      </section>

      <section className="stats-grid">
        {overview.map((item) => (
          <Card key={item.key}>
            <div className="card-header-row">
              <div>
                <div className="eyebrow">{t(`tasks.overview.${item.key}`)}</div>
                <div className="metric-value">
                  {formatNumber(locale, item.value, item.key === "throughput" ? 1 : 0)}
                  {item.unit ? <span className="metric-unit">{item.unit}</span> : null}
                </div>
              </div>
              <div className="metric-icon metric-icon-accent">
                <Workflow className="metric-icon-svg" />
              </div>
            </div>
            <div className="metric-foot">
              <span className="metric-delta">{item.change}</span>
              <span className="metric-copy">{t("tasks.table.subtitle")}</span>
            </div>
          </Card>
        ))}
      </section>

      <section className="tasks-grid">
        <Card>
          <div className="section-header section-header-tight">
            <div>
              <div className="eyebrow">{t("tasks.table.title")}</div>
              <h3 className="section-title">{t("tasks.table.subtitle")}</h3>
            </div>

            <div className="filter-toolbar">
              <div className="search-field">
                <Search className="search-field-icon" />
                <TextField
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t("tasks.searchPlaceholder")}
                />
              </div>
            </div>
          </div>

          <div className="segmented-control" role="tablist" aria-label={t("tasks.title")}>
            {filterValues.map((value) => (
              <button
                key={value}
                type="button"
                className={`segmented-item ${filter === value ? "segmented-item-active" : ""}`}
                onClick={() => setFilter(value)}
              >
                {t(`tasks.filters.${value}`)}
              </button>
            ))}
          </div>

          <div className="table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>{t("tasks.table.columns.task")}</th>
                  <th>{t("tasks.table.columns.subject")}</th>
                  <th>{t("tasks.table.columns.queue")}</th>
                  <th>{t("tasks.table.columns.progress")}</th>
                  <th>{t("tasks.table.columns.model")}</th>
                  <th>{t("tasks.table.columns.created")}</th>
                  <th>{t("tasks.table.columns.latency")}</th>
                  <th>{t("tasks.table.columns.owner")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <div className="table-primary mono">{task.id}</div>
                      <StatusDot tone={statusToneMap[task.status]} label={t(`common.status.${task.status}`)} />
                    </td>
                    <td>{t(`common.${task.subjectKey}`)}</td>
                    <td>{task.queue}</td>
                    <td>
                      <div className="progress-cell">
                        <MeterBar value={task.progress} />
                        <span className="numeric">{task.progress}%</span>
                      </div>
                    </td>
                    <td>{task.model}</td>
                    <td>{formatTimestamp(locale, task.createdAt)}</td>
                    <td className="numeric">
                      {task.latencySeconds ? `${formatNumber(locale, task.latencySeconds)}s` : "—"}
                    </td>
                    <td>{task.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card tone="muted">
          <div className="section-header">
            <div>
              <div className="eyebrow">{t("tasks.logs.title")}</div>
              <h3 className="section-title">{t("tasks.logs.subtitle")}</h3>
            </div>
          </div>

          <div className="log-list">
            {logs.map((log) => (
              <div key={`${log.timestamp}-${log.messageKey}`} className="log-row">
                <span className={`log-level log-level-${log.level}`}>{log.level}</span>
                <span className="log-time mono">{log.timestamp}</span>
                <span className="log-message">{t(log.messageKey)}</span>
              </div>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}
