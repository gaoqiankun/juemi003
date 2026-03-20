import { ArrowUpRight, Database, Download, Layers3 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AdminLocale, ModelStatus } from "@/data/admin-mocks";
import { Badge, Button, Card, MeterBar, StatusDot } from "@/components/ui/primitives";
import { useModelsData } from "@/hooks/use-models-data";
import { formatCompactNumber, formatNumber, formatTimestamp } from "@/lib/admin-format";

const modelStatusTone: Record<ModelStatus, "success" | "warning" | "accent"> = {
  ready: "success",
  syncing: "accent",
  queued: "warning",
};

export function ModelsPage() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en") as AdminLocale;
  const { models, summary } = useModelsData();

  return (
    <div className="page-stack">
      <section className="page-header">
        <div>
          <div className="eyebrow">{t("shell.nav.models")}</div>
          <h2 className="page-title">{t("models.title")}</h2>
        </div>
        <p className="page-description">{t("models.description")}</p>
      </section>

      <section className="stats-grid">
        <SummaryCard label={t("models.summary.ready")} value={formatNumber(locale, summary.ready)} />
        <SummaryCard label={t("models.summary.syncing")} value={formatNumber(locale, summary.syncing)} />
        <SummaryCard label={t("models.summary.queued")} value={formatNumber(locale, summary.queued)} />
        <SummaryCard
          label={t("models.summary.storage")}
          value={`${formatNumber(locale, summary.storageUsedGb, 1)} GB`}
        />
      </section>

      <section className="models-grid">
        {models.map((model) => (
          <Card key={model.id}>
            <div className="card-header-row">
              <div>
                <div className="eyebrow">{t("models.card.provider")}</div>
                <h3 className="section-title">{model.name}</h3>
              </div>
              <StatusDot tone={modelStatusTone[model.status]} label={t(`common.status.${model.status}`)} />
            </div>

            <div className="detail-grid">
              <DetailLine label={t("models.card.provider")} value={model.provider} />
              <DetailLine label={t("models.card.version")} value={model.version} />
              <DetailLine label={t("models.card.footprint")} value={`${formatNumber(locale, model.sizeGb, 1)} GB`} />
              <DetailLine label={t("models.card.minimumVram")} value={`${formatNumber(locale, model.minVramGb)} GB`} />
              <DetailLine
                label={t("models.card.downloads")}
                value={formatCompactNumber(locale, model.downloads)}
              />
              <DetailLine label={t("models.card.updated")} value={formatTimestamp(locale, model.updatedAt)} />
            </div>

            {model.status !== "ready" ? (
              <div className="gpu-meter-block">
                <div className="meter-meta">
                  <span>{t("models.card.syncProgress")}</span>
                  <span className="numeric">{model.progress}%</span>
                </div>
                <MeterBar value={model.progress} />
              </div>
            ) : null}

            <div className="badge-row">
              {model.capabilities.map((capability) => (
                <Badge key={capability}>{t(`common.${capability}`)}</Badge>
              ))}
            </div>
          </Card>
        ))}

        <Card tone="muted" className="import-card">
          <div className="import-card-icon">
            <Layers3 className="section-icon" />
          </div>
          <div>
            <div className="eyebrow">{t("common.importModel")}</div>
            <h3 className="section-title">{t("models.importTitle")}</h3>
            <p className="section-description">{t("models.importCopy")}</p>
          </div>
          <div className="import-card-meta">
            <div className="detail-chip">
              <Database className="detail-icon" />
              <span>manifest.json</span>
            </div>
            <div className="detail-chip">
              <Download className="detail-icon" />
              <span>sha256 / checksums</span>
            </div>
          </div>
          <Button variant="primary">
            {t("common.importModel")}
            <ArrowUpRight className="button-icon" />
          </Button>
        </Card>
      </section>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <div className="eyebrow">{label}</div>
      <div className="metric-value">{value}</div>
    </Card>
  );
}

function DetailLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <div className="detail-label">{label}</div>
      <div className="detail-value">{value}</div>
    </div>
  );
}
