import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/primitives";
import type { AdminPendingItem } from "@/hooks/use-models-data";

interface FirstRunWizardProps {
  defaultPendingItem: AdminPendingItem | null;
  onStartDownload: (item: AdminPendingItem) => void;
}

export function FirstRunWizard({ defaultPendingItem, onStartDownload }: FirstRunWizardProps) {
  const { t } = useTranslation();

  if (!defaultPendingItem) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <p className="text-sm font-semibold text-text-primary">{t("models.firstRun.title")}</p>
        <p className="text-xs text-text-secondary">{t("models.firstRun.description")}</p>
      </div>
    );
  }

  const isAlreadyDownloading = defaultPendingItem.downloadStatus !== "pending";

  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center">
      <p className="text-sm font-semibold text-text-primary">{defaultPendingItem.displayName}</p>
      <p className="text-xs text-text-secondary">{t("models.firstRun.description")}</p>
      {isAlreadyDownloading ? (
        <div className="w-full max-w-xs grid gap-1.5">
          <p className="text-xs text-text-muted">{t("models.firstRun.downloading")}</p>
          <Progress value={defaultPendingItem.downloadProgress} />
        </div>
      ) : (
        <Button
          type="button"
          size="sm"
          variant="primary"
          onClick={() => onStartDownload(defaultPendingItem)}
        >
          <Download className="mr-1 h-3.5 w-3.5" />
          {t("models.firstRun.startDownload")}
        </Button>
      )}
    </div>
  );
}
