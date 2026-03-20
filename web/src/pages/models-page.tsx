import type { ReactNode } from "react";
import { ArrowUpRight, Database, Download, Layers3 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, MeterBar, StatusDot } from "@/components/ui/primitives";
import type { AdminLocale, ModelStatus } from "@/data/admin-mocks";
import { useModelsData } from "@/hooks/use-models-data";
import { formatCompactNumber, formatNumber, formatTimestamp } from "@/lib/admin-format";

const modelStatusTone: Record<ModelStatus, "success" | "warning" | "accent"> = {
  ready: "success",
  syncing: "accent",
  queued: "warning",
};

const eyebrowClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";

export function ModelsPage() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en") as AdminLocale;
  const { models, summary } = useModelsData();

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className={eyebrowClassName}>{t("shell.nav.models")}</div>
          <h2 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-text-primary">{t("models.title")}</h2>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label={t("models.summary.ready")} value={formatNumber(locale, summary.ready)} />
        <SummaryCard label={t("models.summary.syncing")} value={formatNumber(locale, summary.syncing)} />
        <SummaryCard label={t("models.summary.queued")} value={formatNumber(locale, summary.queued)} />
        <SummaryCard
          label={t("models.summary.storage")}
          value={`${formatNumber(locale, summary.storageUsedGb, 1)} GB`}
        />
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {models.map((model) => (
          <Card key={model.id} className="grid gap-5 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className={eyebrowClassName}>{t("models.card.provider")}</div>
                <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">{model.name}</h3>
              </div>
              <StatusDot tone={modelStatusTone[model.status]} label={t(`common.status.${model.status}`)} />
            </div>

            <div className="grid gap-3">
              <DetailLine label={t("models.card.provider")} value={model.provider} />
              <DetailLine label={t("models.card.version")} value={model.version} />
              <DetailLine label={t("models.card.footprint")} value={`${formatNumber(locale, model.sizeGb, 1)} GB`} />
              <DetailLine label={t("models.card.minimumVram")} value={`${formatNumber(locale, model.minVramGb)} GB`} />
              <DetailLine label={t("models.card.downloads")} value={formatCompactNumber(locale, model.downloads)} />
              <DetailLine label={t("models.card.updated")} value={formatTimestamp(locale, model.updatedAt)} />
            </div>

            {model.status !== "ready" ? (
              <div className="grid gap-2">
                <div className="flex items-center justify-between gap-4 text-sm text-text-secondary">
                  <span>{t("models.card.syncProgress")}</span>
                  <span className="font-mono text-text-primary">{model.progress}%</span>
                </div>
                <MeterBar value={model.progress} />
              </div>
            ) : null}

            <div className="flex flex-wrap gap-2">
              {model.capabilities.map((capability) => (
                <Badge key={capability}>{t(`common.${capability}`)}</Badge>
              ))}
            </div>
          </Card>
        ))}

        <Card tone="low" className="grid content-start gap-5 p-5">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-outline bg-surface-container text-accent-strong">
            <Layers3 className="h-6 w-6" />
          </div>

          <div>
            <div className={eyebrowClassName}>{t("common.importModel")}</div>
            <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-text-primary">{t("models.importTitle")}</h3>
          </div>

          <div className="grid gap-3">
            <Chip icon={<Database className="h-4 w-4" />} label={t("models.importMeta.manifest")} />
            <Chip icon={<Download className="h-4 w-4" />} label={t("models.importMeta.checksums")} />
          </div>

          <Button variant="primary">
            {t("common.importModel")}
            <ArrowUpRight className="h-4 w-4" />
          </Button>
        </Card>
      </section>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <Card className="grid gap-2 p-5">
      <div className={eyebrowClassName}>{label}</div>
      <div className="text-3xl font-semibold tracking-[-0.04em] text-text-primary">{value}</div>
    </Card>
  );
}

function DetailLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-2 rounded-xl border border-outline bg-surface-container-low p-4">
      <div className="text-sm text-text-muted">{label}</div>
      <div className="text-sm font-semibold text-text-primary">{value}</div>
    </div>
  );
}

function Chip({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-outline bg-surface-container-highest px-3 py-1.5 text-sm text-text-secondary">
      {icon}
      <span>{label}</span>
    </div>
  );
}
