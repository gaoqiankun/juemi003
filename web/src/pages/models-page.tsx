import { useCallback, useState } from "react";
import { Plus, X, RotateCcw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AddModelDialog } from "@/components/add-model-dialog";
import { Progress } from "@/components/ui/progress";
import { Badge, Button, Card, ToggleSwitch } from "@/components/ui/primitives";
import { useModelsData, type AdminModelItem, type AdminModelRuntimeState, type AdminPendingItem } from "@/hooks/use-models-data";

const tableHeadBaseClassName = "px-4 pb-2 font-display text-[11px] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableHeadLeftClassName = `${tableHeadBaseClassName} text-left`;
const tableHeadCenterClassName = `${tableHeadBaseClassName} text-center`;
const tableCellBaseClassName = "bg-surface-container-lowest px-4 py-2.5 align-middle text-sm text-text-secondary first:rounded-l-lg last:rounded-r-lg";
const tableCellLeftClassName = `${tableCellBaseClassName} text-left`;
const tableCellCenterClassName = `${tableCellBaseClassName} text-center`;

const runtimeToneMap: Record<AdminModelRuntimeState, "success" | "warning" | "danger" | "neutral"> = {
  ready: "success",
  loading: "warning",
  not_loaded: "neutral",
  error: "danger",
  unknown: "neutral",
};

const sourceLabelMap: Record<string, string> = {
  huggingface: "HF",
  local: "Local",
  url: "URL",
};

function formatSpeedBps(bps: number): string {
  if (bps <= 0) return "";
  const mbps = bps / (1024 * 1024);
  return `${mbps.toFixed(1)} MB/s`;
}

function truncatePath(path: string, maxLen = 32): string {
  if (path.length <= maxLen) return path;
  return `…${path.slice(-(maxLen - 1))}`;
}

function PendingRow({
  item,
  onCancel,
  onRetry,
  onRemove,
}: {
  item: AdminPendingItem;
  onCancel: (id: string) => void;
  onRetry: (item: AdminPendingItem) => void;
  onRemove: (id: string) => void;
}) {
  const { t } = useTranslation();
  const speed = formatSpeedBps(item.downloadSpeedBps);

  return (
    <div className="grid gap-2 rounded-xl border border-outline bg-surface-container-lowest p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="grid gap-0.5">
          <span className="text-sm font-semibold text-text-primary">{item.displayName}</span>
          <span
            className="max-w-[320px] truncate text-xs text-text-secondary"
            title={item.modelPath}
          >
            {item.modelPath}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {item.downloadStatus === "downloading" ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onCancel(item.id)}
            >
              <X className="mr-1 h-3.5 w-3.5" />
              {t("models.pending.cancel")}
            </Button>
          ) : (
            <>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => onRetry(item)}
              >
                <RotateCcw className="mr-1 h-3.5 w-3.5" />
                {t("models.pending.retry")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="danger"
                onClick={() => onRemove(item.id)}
              >
                <Trash2 className="mr-1 h-3.5 w-3.5" />
                {t("models.pending.remove")}
              </Button>
            </>
          )}
        </div>
      </div>

      {item.downloadStatus === "downloading" ? (
        <div className="grid gap-1">
          <Progress value={item.downloadProgress} />
          <div className="flex items-center justify-between text-xs text-text-secondary">
            <span>{item.downloadProgress}%</span>
            {speed ? <span>{speed}</span> : null}
          </div>
        </div>
      ) : (
        <p className="text-xs text-danger-text">
          {item.downloadError || t("models.pending.unknownError")}
        </p>
      )}
    </div>
  );
}

export function ModelsPage() {
  const { t } = useTranslation();
  const {
    models,
    pendingItems,
    loading,
    error,
    busyModelId,
    setModelEnabled,
    setModelDefault,
    requestModelLoad,
    addModel,
    cancelDownload,
    removeModel,
    retryDownload,
  } = useModelsData();
  const [actionError, setActionError] = useState("");
  const [addDialogOpen, setAddDialogOpen] = useState(false);

  const runModelAction = useCallback(async (action: () => Promise<void>) => {
    try {
      setActionError("");
      await action();
    } catch (modelActionError) {
      setActionError(modelActionError instanceof Error ? modelActionError.message : String(modelActionError));
    }
  }, []);

  const handleToggleModel = useCallback((model: AdminModelItem, nextValue: boolean) => {
    runModelAction(() => setModelEnabled(model.id, nextValue));
  }, [runModelAction, setModelEnabled]);

  const handleSetDefault = useCallback((model: AdminModelItem) => {
    runModelAction(() => setModelDefault(model.id));
  }, [runModelAction, setModelDefault]);

  const handleLoadOrRetry = useCallback((model: AdminModelItem) => {
    runModelAction(() => requestModelLoad(model.id));
  }, [requestModelLoad, runModelAction]);

  const handleAddModel = useCallback(async (data: Record<string, unknown>) => {
    await addModel(data);
  }, [addModel]);

  const handleCancel = useCallback((id: string) => {
    runModelAction(() => cancelDownload(id));
  }, [runModelAction, cancelDownload]);

  const handleRemove = useCallback((id: string) => {
    runModelAction(() => removeModel(id));
  }, [runModelAction, removeModel]);

  const handleRetry = useCallback((item: AdminPendingItem) => {
    runModelAction(() =>
      retryDownload(item.id, {
        id: item.id,
        displayName: item.displayName,
        modelPath: item.modelPath,
        weightSource: item.weightSource,
        providerType: item.providerType,
      }),
    );
  }, [runModelAction, retryDownload]);

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error) return <div className="flex items-center justify-center h-full text-red-500">{error}</div>;

  const hasPending = pendingItems.length > 0;

  return (
    <div className="grid gap-4">
      <Card className="grid gap-3 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-[-0.03em] text-text-primary">{t("models.list.title")}</h2>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setAddDialogOpen(true)}
          >
            <Plus className="mr-1 h-3.5 w-3.5" />
            {t("models.list.addModel")}
          </Button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] table-fixed border-separate border-spacing-y-2">
            <colgroup>
              <col className="w-[34%]" />
              <col className="w-[20%]" />
              <col className="w-[14%]" />
              <col className="w-[32%]" />
            </colgroup>
            <thead>
              <tr>
                <th className={tableHeadLeftClassName}>{t("models.list.columns.name")}</th>
                <th className={tableHeadCenterClassName}>{t("models.list.columns.runtime")}</th>
                <th className={tableHeadCenterClassName}>{t("models.list.columns.slotUsage")}</th>
                <th className={tableHeadCenterClassName}>{t("models.list.columns.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {models.length === 0 ? (
                <tr>
                  <td className={tableCellLeftClassName} colSpan={4}>
                    {t("models.list.empty")}
                  </td>
                </tr>
              ) : models.map((model) => {
                const isBusy = busyModelId === model.id;
                const runtimeErrorTooltip = model.runtimeState === "error" && model.errorMessage
                  ? model.errorMessage
                  : undefined;
                const sourceLabel = sourceLabelMap[model.weightSource] ?? model.weightSource;
                const truncated = truncatePath(model.modelPath);
                return (
                  <tr key={model.id}>
                    <td className={tableCellLeftClassName}>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <div className="text-sm font-semibold text-text-primary">{model.displayName}</div>
                        {model.isDefault ? (
                          <Badge tone="accent">{t("models.list.defaultTag")}</Badge>
                        ) : null}
                        <Badge tone="neutral">{sourceLabel}</Badge>
                      </div>
                      {model.modelPath ? (
                        <div
                          className="mt-0.5 truncate text-xs text-text-muted"
                          title={model.modelPath}
                        >
                          {truncated}
                        </div>
                      ) : null}
                    </td>
                    <td className={tableCellCenterClassName}>
                      <div className="grid justify-items-center">
                        <Badge
                          tone={runtimeToneMap[model.runtimeState]}
                          title={runtimeErrorTooltip}
                          className={runtimeErrorTooltip ? "cursor-help" : ""}
                        >
                          {t(`models.runtime.${model.runtimeState}`)}
                        </Badge>
                      </div>
                    </td>
                    <td className={tableCellCenterClassName}>
                      {model.runtimeState === "ready"
                        ? `${model.tasksProcessed} / ${model.maxTasksPerSlot}`
                        : "—"}
                    </td>
                    <td className={tableCellCenterClassName}>
                      <div className="flex items-center justify-center gap-2">
                        <div className="inline-flex items-center gap-1.5">
                          <ToggleSwitch
                            checked={model.isEnabled}
                            onChange={(nextValue) => handleToggleModel(model, nextValue)}
                            label={t("models.list.toggleLabel", { name: model.displayName })}
                            className="data-[state=checked]:bg-success-text"
                          />
                          <span className="text-xs font-semibold tracking-wide text-text-primary">
                            {t(model.isEnabled ? "models.list.enabled" : "models.list.disabled")}
                          </span>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={isBusy || model.isDefault}
                          onClick={() => handleSetDefault(model)}
                        >
                          {t("models.list.setDefault")}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={isBusy || model.runtimeState === "ready" || model.runtimeState === "loading"}
                          onClick={() => handleLoadOrRetry(model)}
                        >
                          {t("models.list.load")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {actionError ? <p className="text-sm text-danger-text">{actionError}</p> : null}
      </Card>

      {hasPending ? (
        <Card className="grid gap-3 p-4">
          <h2 className="text-lg font-semibold tracking-[-0.03em] text-text-primary">
            {t("models.pending.title")}
          </h2>
          <div className="grid gap-2">
            {pendingItems.map((item) => (
              <PendingRow
                key={item.id}
                item={item}
                onCancel={handleCancel}
                onRetry={handleRetry}
                onRemove={handleRemove}
              />
            ))}
          </div>
        </Card>
      ) : null}

      <AddModelDialog
        open={addDialogOpen}
        onOpenChange={setAddDialogOpen}
        onSubmit={handleAddModel}
      />
    </div>
  );
}
