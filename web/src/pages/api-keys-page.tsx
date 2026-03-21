import type { ReactNode } from "react";
import { CopyPlus, ShieldCheck, ShieldEllipsis } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, StatusDot } from "@/components/ui/primitives";
import type { AdminLocale, KeyStatus } from "@/data/admin-mocks";
import { useApiKeysData } from "@/hooks/use-api-keys-data";
import {
  formatCompactNumber,
  formatCurrency,
  formatPercent,
  formatTimestamp,
  maskKey,
} from "@/lib/admin-format";

const keyStatusTones: Record<KeyStatus, "success" | "warning" | "neutral"> = {
  active: "success",
  rotating: "warning",
  paused: "neutral",
};

const eyebrowClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableHeadClassName = "px-4 pb-2 text-left font-display text-[11px] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableCellClassName = "bg-surface-container-lowest px-4 py-3 align-top text-sm text-text-secondary first:rounded-l-lg last:rounded-r-lg";

export function ApiKeysPage() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en") as AdminLocale;
  const { data, loading, error } = useApiKeysData();

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error || !data) return <div className="flex items-center justify-center h-full text-red-500">{error || "Failed to load"}</div>;

  const { usage, keys } = data;

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className={eyebrowClassName}>{t("shell.nav.apiKeys")}</div>
          <h2 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-text-primary">{t("apiKeys.title")}</h2>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {usage.map((metric) => (
          <Card key={metric.key} className="grid gap-2 p-5">
            <div className={eyebrowClassName}>{t(`apiKeys.usage.${metric.key}`)}</div>
            <div className="text-3xl font-semibold tracking-[-0.04em] text-text-primary">
              {formatUsage(locale, metric.key, metric.value)}
            </div>
          </Card>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_22rem]">
        <Card className="grid gap-5 p-5">
          <div>
            <div className={eyebrowClassName}>{t("apiKeys.table.title")}</div>
            <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">
              {t("apiKeys.table.subtitle")}
            </h3>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] border-separate border-spacing-y-2">
              <thead>
                <tr>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.name")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.token")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.created")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.lastUsed")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.requests")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.scopes")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.status")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.owner")}</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.id}>
                    <td className={tableCellClassName}>
                      <div className="text-sm font-semibold text-text-primary">{key.name}</div>
                      <div className="mt-1 font-mono text-xs text-text-muted">{key.id}</div>
                    </td>
                    <td className={`${tableCellClassName} font-mono`}>{maskKey(key.prefix)}</td>
                    <td className={tableCellClassName}>{formatTimestamp(locale, key.createdAt)}</td>
                    <td className={tableCellClassName}>{formatTimestamp(locale, key.lastUsedAt)}</td>
                    <td className={`${tableCellClassName} font-mono`}>{formatCompactNumber(locale, key.requests)}</td>
                    <td className={tableCellClassName}>
                      <div className="flex flex-wrap gap-2">
                        {key.scopes.map((scope) => (
                          <Badge key={scope}>{scope}</Badge>
                        ))}
                      </div>
                    </td>
                    <td className={tableCellClassName}>
                      <StatusDot tone={keyStatusTones[key.status]} label={t(`common.status.${key.status}`)} />
                    </td>
                    <td className={tableCellClassName}>{key.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card tone="low" className="grid content-start gap-5 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className={eyebrowClassName}>{t("apiKeys.createPanel.title")}</div>
              <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">
                {t("apiKeys.createPanel.copy")}
              </h3>
            </div>
            <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-outline bg-surface-container text-accent-strong">
              <ShieldCheck className="h-5 w-5" />
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Badge tone="accent">{t("apiKeys.createPanel.scopes.tasksRead")}</Badge>
            <Badge tone="accent">{t("apiKeys.createPanel.scopes.tasksWrite")}</Badge>
            <Badge tone="accent">{t("apiKeys.createPanel.scopes.modelsRead")}</Badge>
            <Badge>{t("apiKeys.createPanel.scopes.keysRead")}</Badge>
          </div>

          <div className="grid gap-3">
            <ActionCard
              icon={<ShieldEllipsis className="h-4 w-4 text-warning-text" />}
              label={t("apiKeys.actions.rotate")}
              value={t("apiKeys.actions.rotateHelper")}
            />
            <ActionCard
              icon={<CopyPlus className="h-4 w-4 text-accent-strong" />}
              label={t("apiKeys.actions.disable")}
              value={t("apiKeys.actions.disableHelper")}
            />
          </div>

          <Button variant="primary">{t("common.createKey")}</Button>
        </Card>
      </section>
    </div>
  );
}

function ActionCard({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="grid gap-2 rounded-xl border border-outline bg-surface-container px-4 py-4">
      <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
        {icon}
        <span>{label}</span>
      </div>
      <div className="text-sm leading-6 text-text-secondary">{value}</div>
    </div>
  );
}

function formatUsage(locale: AdminLocale, key: string, value: number) {
  if (key === "spend") {
    return formatCurrency(locale, value);
  }

  if (key === "errorRate") {
    return formatPercent(locale, value, 2);
  }

  return formatCompactNumber(locale, value);
}
