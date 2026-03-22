import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, StatusDot, TextField } from "@/components/ui/primitives";
import type { AdminLocale } from "@/data/admin-mocks";
import { type CreatedApiKey, useApiKeysData } from "@/hooks/use-api-keys-data";
import {
  formatCompactNumber,
  formatTimestamp,
} from "@/lib/admin-format";

const eyebrowClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableHeadClassName = "px-4 pb-2 text-left font-display text-[11px] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableCellClassName = "bg-surface-container-lowest px-4 py-3 align-top text-sm text-text-secondary first:rounded-l-lg last:rounded-r-lg";

export function ApiKeysPage() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en") as AdminLocale;
  const {
    keys,
    loading,
    error,
    isCreating,
    activeCount,
    createKey,
  } = useApiKeysData();
  const [label, setLabel] = useState("");
  const [createError, setCreateError] = useState("");
  const [createdKey, setCreatedKey] = useState<CreatedApiKey | null>(null);

  const handleCreateKey = useCallback(async () => {
    const nextLabel = label.trim();
    if (!nextLabel) {
      setCreateError(t("apiKeys.createPanel.missingLabel"));
      return;
    }
    try {
      const created = await createKey(nextLabel);
      setCreateError("");
      setCreatedKey(created);
      setLabel("");
    } catch (createKeyError) {
      setCreateError(createKeyError instanceof Error ? createKeyError.message : String(createKeyError));
    }
  }, [createKey, label, t]);

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error) return <div className="flex items-center justify-center h-full text-red-500">{error}</div>;

  return (
    <div className="grid gap-6">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="grid gap-2 p-5">
          <div className={eyebrowClassName}>{t("apiKeys.summary.activeKeys")}</div>
          <div className="text-3xl font-semibold tracking-[-0.04em] text-text-primary">
            {formatCompactNumber(locale, activeCount)}
          </div>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_22rem]">
        <Card className="grid gap-5 p-5">
          <h2 className="text-lg font-semibold tracking-[-0.03em] text-text-primary">{t("apiKeys.table.title")}</h2>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-separate border-spacing-y-2">
              <thead>
                <tr>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.name")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.token")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.created")}</th>
                  <th className={tableHeadClassName}>{t("apiKeys.table.columns.status")}</th>
                </tr>
              </thead>
              <tbody>
                {keys.length === 0 ? (
                  <tr>
                    <td className={tableCellClassName} colSpan={4}>
                      {t("apiKeys.table.empty")}
                    </td>
                  </tr>
                ) : keys.map((key) => (
                  <tr key={key.id}>
                    <td className={tableCellClassName}>
                      <div className="text-sm font-semibold text-text-primary">{key.label}</div>
                    </td>
                    <td className={`${tableCellClassName} font-mono`}>{key.id}</td>
                    <td className={tableCellClassName}>{formatTimestamp(locale, key.createdAt)}</td>
                    <td className={tableCellClassName}>
                      <StatusDot
                        tone={key.isActive ? "success" : "neutral"}
                        label={t(`common.status.${key.isActive ? "active" : "paused"}`)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card tone="low" className="grid content-start gap-4 p-5">
          <div className="grid gap-1">
            <h2 className="text-lg font-semibold tracking-[-0.03em] text-text-primary">{t("common.createKey")}</h2>
            <p className="text-sm text-text-secondary">{t("apiKeys.createPanel.shortCopy")}</p>
          </div>

          <label className="grid gap-1.5 text-sm text-text-secondary" htmlFor="admin-key-label">
            <span>{t("apiKeys.createPanel.labelField")}</span>
            <TextField
              id="admin-key-label"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder={t("apiKeys.createPanel.labelPlaceholder")}
            />
          </label>

          <Button type="button" variant="primary" disabled={isCreating} onClick={handleCreateKey}>
            {isCreating ? t("apiKeys.createPanel.creating") : t("common.createKey")}
          </Button>

          {createError ? (
            <p className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger-text">
              {createError}
            </p>
          ) : null}

          {createdKey ? (
            <div className="grid gap-2 rounded-xl border border-outline bg-surface-container px-3 py-3">
              <p className="text-xs text-text-secondary">{t("apiKeys.createPanel.createdNotice")}</p>
              <p className="font-mono text-xs text-text-primary break-all">{createdKey.token}</p>
            </div>
          ) : null}
        </Card>
      </section>
    </div>
  );
}
