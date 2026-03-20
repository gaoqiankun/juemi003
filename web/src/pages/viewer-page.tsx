import { ArrowLeft, Download } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, StatusDot } from "@/components/ui/primitives";
import { useViewerData } from "@/hooks/use-viewer-data";
import { formatTimestamp } from "@/lib/admin-format";

export function ViewerPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en";
  const { taskId = "gen_8de14a11" } = useParams();
  const { activeTask, detailItems } = useViewerData(taskId);
  const qualityLabelMap = {
    draft: t("user.generate.options.qualityDraft"),
    production: t("user.generate.options.qualityProduction"),
    ultra: t("user.generate.options.qualityUltra"),
  } as const;

  return (
    <div className="page-stack">
      <section className="page-header">
        <div>
          <div className="eyebrow">{t("user.viewer.title")}</div>
          <h2 className="page-title">{t(activeTask.titleKey)}</h2>
        </div>
        <Link to="/generations">
          <Button variant="secondary">
            <ArrowLeft className="button-icon" />
            {t("user.viewer.backButton")}
          </Button>
        </Link>
      </section>

      <section className="viewer-grid">
        <Card className="viewer-stage-card">
          <div className="viewer-stage">
            <div className="viewer-placeholder">
              <div className="eyebrow">3D Preview</div>
              <div className="page-title">{t("user.viewer.previewPlaceholder")}</div>
            </div>
          </div>
        </Card>

        <Card tone="muted">
          <div className="section-header">
            <div>
              <div className="eyebrow">{t("user.viewer.panelLabel")}</div>
              <h3 className="section-title mono">{activeTask.id}</h3>
            </div>
            <StatusDot
              tone={activeTask.status === "completed" ? "success" : "accent"}
              label={t(`user.status.${activeTask.status}`)}
            />
          </div>

          <div className="detail-grid">
            {detailItems.map((item) => (
              <div key={item.labelKey} className="detail-item">
                <div className="detail-label">{t(item.labelKey)}</div>
                <div className="detail-value">
                  {item.labelKey === "user.viewer.details.quality"
                    ? qualityLabelMap[activeTask.quality]
                    : item.value}
                </div>
              </div>
            ))}
            <div className="detail-item">
              <div className="detail-label">{t("user.viewer.details.updated")}</div>
              <div className="detail-value">{formatTimestamp(locale, activeTask.updatedAt)}</div>
            </div>
          </div>

          <div className="badge-row">
            {activeTask.downloadFormats.map((format) => (
              <Badge key={format} tone="accent">{format.toUpperCase()}</Badge>
            ))}
          </div>

          <div className="download-list">
            {activeTask.downloadFormats.map((format) => (
              <Button key={format} variant="secondary" className="full-width-button">
                <Download className="button-icon" />
                {t("user.viewer.downloadFormat", { format: format.toUpperCase() })}
              </Button>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}
