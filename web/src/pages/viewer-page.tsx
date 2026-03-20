import { ArrowLeft, Download } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, StatusDot } from "@/components/ui/primitives";
import { useViewerData } from "@/hooks/use-viewer-data";
import { formatTimestamp } from "@/lib/admin-format";

const eyebrowClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";

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
    <div className="grid gap-6">
      <section className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <div className={eyebrowClassName}>{t("user.viewer.title")}</div>
          <h2 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-text-primary">{t(activeTask.titleKey)}</h2>
        </div>
        <Button variant="secondary" asChild>
          <Link to="/gallery">
            <ArrowLeft className="h-4 w-4" />
            {t("user.viewer.backButton")}
          </Link>
        </Button>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_24rem]">
        <Card className="min-h-[40rem] overflow-hidden p-0">
          <div className="flex h-full min-h-[40rem] items-center justify-center bg-[image:var(--page-gradient)] bg-surface-container-low px-8 text-center">
            <div className="grid gap-3">
              <div className={eyebrowClassName}>{t("user.viewer.previewLabel")}</div>
              <div className="text-3xl font-semibold tracking-[-0.04em] text-text-primary">
                {t("user.viewer.previewPlaceholder")}
              </div>
            </div>
          </div>
        </Card>

        <Card tone="low" className="grid content-start gap-5 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className={eyebrowClassName}>{t("user.viewer.panelLabel")}</div>
              <h3 className="mt-1 font-mono text-lg font-semibold text-text-primary">{activeTask.id}</h3>
            </div>
            <StatusDot
              tone={activeTask.status === "completed" ? "success" : "accent"}
              label={t(`user.status.${activeTask.status}`)}
            />
          </div>

          <div className="grid gap-3">
            {detailItems.map((item) => (
              <div key={item.labelKey} className="grid gap-2 rounded-xl border border-outline bg-surface-container px-4 py-4">
                <div className="text-sm text-text-muted">{t(item.labelKey)}</div>
                <div className="text-sm font-semibold text-text-primary">
                  {item.labelKey === "user.viewer.details.quality"
                    ? qualityLabelMap[activeTask.quality]
                    : item.value}
                </div>
              </div>
            ))}
            <div className="grid gap-2 rounded-xl border border-outline bg-surface-container px-4 py-4">
              <div className="text-sm text-text-muted">{t("user.viewer.details.updated")}</div>
              <div className="text-sm font-semibold text-text-primary">{formatTimestamp(locale, activeTask.updatedAt)}</div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {activeTask.downloadFormats.map((format) => (
              <Badge key={format} tone="accent">{format.toUpperCase()}</Badge>
            ))}
          </div>

          <div className="grid gap-3">
            {activeTask.downloadFormats.map((format) => (
              <Button key={format} variant="secondary" className="w-full justify-center">
                <Download className="h-4 w-4" />
                {t("user.viewer.downloadFormat", { format: format.toUpperCase() })}
              </Button>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}
