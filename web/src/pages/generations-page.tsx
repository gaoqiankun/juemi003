import { useState } from "react";
import { Download, Eye } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { UserGenerationStatus } from "@/data/user-mocks";
import { Button, Card, StatusDot } from "@/components/ui/primitives";
import { useGenerationsData } from "@/hooks/use-generations-data";
import { formatTimestamp } from "@/lib/admin-format";

const statusToneMap: Record<UserGenerationStatus, "accent" | "success" | "danger"> = {
  processing: "accent",
  completed: "success",
  failed: "danger",
};

export function GenerationsPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en";
  const { filters, records } = useGenerationsData();
  const [filter, setFilter] = useState<"all" | UserGenerationStatus>("all");

  const filteredRecords = records.filter((item) => filter === "all" || item.status === filter);

  return (
    <div className="page-stack">
      <section className="page-header">
        <div>
          <div className="eyebrow">{t("user.shell.nav.generations")}</div>
          <h2 className="page-title">{t("user.generations.title")}</h2>
        </div>
        <p className="page-description">{t("user.generations.description")}</p>
      </section>

      <section className="section-stack">
        <div className="segmented-control" role="tablist" aria-label={t("user.generations.title")}>
          {filters.map((item) => (
            <button
              key={item.value}
              type="button"
              className={`segmented-item ${filter === item.value ? "segmented-item-active" : ""}`}
              onClick={() => setFilter(item.value)}
            >
              {t(item.labelKey)}
            </button>
          ))}
        </div>

        {filteredRecords.length ? (
          <div className="generation-grid">
            {filteredRecords.map((record) => (
              <Card key={record.id}>
                <div className="generation-thumb">
                  <span>{t("user.viewer.previewPlaceholder")}</span>
                </div>

                <div className="card-header-row">
                  <div>
                    <div className="table-primary">{t(record.titleKey)}</div>
                    <div className="table-secondary">{formatTimestamp(locale, record.updatedAt)}</div>
                  </div>
                  <StatusDot tone={statusToneMap[record.status]} label={t(`user.status.${record.status}`)} />
                </div>

                <div className="detail-grid">
                  <div className="detail-item">
                    <div className="detail-label">{t("user.generations.card.prompt")}</div>
                    <div className="detail-value">{t(record.promptKey)}</div>
                  </div>
                </div>

                <div className="button-row">
                  <Link to={`/viewer/${record.id}`} className="button-row-item">
                    <Button variant="secondary" className="full-width-button">
                      <Eye className="button-icon" />
                      {t("user.generations.actions.view")}
                    </Button>
                  </Link>
                  <Button variant="ghost">
                    <Download className="button-icon" />
                    {t("user.generations.actions.download")}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <Card tone="muted" className="empty-state-card">
            <div className="empty-state-title">{t("user.generations.emptyTitle")}</div>
            <p className="section-description">{t("user.generations.emptyCopy")}</p>
          </Card>
        )}
      </section>
    </div>
  );
}
