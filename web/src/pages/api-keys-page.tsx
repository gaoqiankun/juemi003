import { CopyPlus, ShieldCheck, ShieldEllipsis } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AdminLocale, KeyStatus } from "@/data/admin-mocks";
import { Badge, Button, Card, StatusDot } from "@/components/ui/primitives";
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

export function ApiKeysPage() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en") as AdminLocale;
  const { usage, keys } = useApiKeysData();

  return (
    <div className="page-stack">
      <section className="page-header">
        <div>
          <div className="eyebrow">{t("shell.nav.apiKeys")}</div>
          <h2 className="page-title">{t("apiKeys.title")}</h2>
        </div>
        <p className="page-description">{t("apiKeys.description")}</p>
      </section>

      <section className="stats-grid">
        {usage.map((metric) => (
          <Card key={metric.key}>
            <div className="eyebrow">{t(`apiKeys.usage.${metric.key}`)}</div>
            <div className="metric-value">{formatUsage(locale, metric.key, metric.value)}</div>
          </Card>
        ))}
      </section>

      <section className="api-keys-grid">
        <Card>
          <div className="section-header">
            <div>
              <div className="eyebrow">{t("apiKeys.table.title")}</div>
              <h3 className="section-title">{t("apiKeys.table.subtitle")}</h3>
            </div>
          </div>

          <div className="table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>{t("apiKeys.table.columns.name")}</th>
                  <th>{t("apiKeys.table.columns.token")}</th>
                  <th>{t("apiKeys.table.columns.created")}</th>
                  <th>{t("apiKeys.table.columns.lastUsed")}</th>
                  <th>{t("apiKeys.table.columns.requests")}</th>
                  <th>{t("apiKeys.table.columns.scopes")}</th>
                  <th>{t("apiKeys.table.columns.status")}</th>
                  <th>{t("apiKeys.table.columns.owner")}</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.id}>
                    <td>
                      <div className="table-primary">{key.name}</div>
                      <div className="table-secondary mono">{key.id}</div>
                    </td>
                    <td className="mono">{maskKey(key.prefix)}</td>
                    <td>{formatTimestamp(locale, key.createdAt)}</td>
                    <td>{formatTimestamp(locale, key.lastUsedAt)}</td>
                    <td className="numeric">{formatCompactNumber(locale, key.requests)}</td>
                    <td>
                      <div className="badge-row">
                        {key.scopes.map((scope) => (
                          <Badge key={scope}>{scope}</Badge>
                        ))}
                      </div>
                    </td>
                    <td>
                      <StatusDot tone={keyStatusTones[key.status]} label={t(`common.status.${key.status}`)} />
                    </td>
                    <td>{key.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card tone="muted">
          <div className="section-header">
            <div>
              <div className="eyebrow">{t("apiKeys.createPanel.title")}</div>
              <h3 className="section-title">{t("apiKeys.createPanel.copy")}</h3>
            </div>
            <ShieldCheck className="section-icon" />
          </div>

          <div className="badge-row">
            <Badge tone="accent">{t("apiKeys.createPanel.scopes.tasksRead")}</Badge>
            <Badge tone="accent">{t("apiKeys.createPanel.scopes.tasksWrite")}</Badge>
            <Badge tone="accent">{t("apiKeys.createPanel.scopes.modelsRead")}</Badge>
            <Badge>{t("apiKeys.createPanel.scopes.keysRead")}</Badge>
          </div>

          <div className="detail-grid detail-grid-two">
            <div className="detail-item">
              <div className="detail-label">
                <ShieldEllipsis className="detail-icon" />
                <span>{t("apiKeys.actions.rotate")}</span>
              </div>
              <div className="detail-value">Grace window 24h</div>
            </div>
            <div className="detail-item">
              <div className="detail-label">
                <CopyPlus className="detail-icon" />
                <span>{t("apiKeys.actions.disable")}</span>
              </div>
              <div className="detail-value">Instant revocation</div>
            </div>
          </div>

          <Button variant="primary">{t("common.createKey")}</Button>
        </Card>
      </section>
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
