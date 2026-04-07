import { useCallback, useRef, useState } from "react";
import { Plus, X, RotateCcw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AddModelDialog } from "@/components/add-model-dialog";
import { FirstRunWizard } from "@/components/first-run-wizard";
import { Progress } from "@/components/ui/progress";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  ToggleSwitch,
} from "@/components/ui/primitives";
import {
  fetchModelDeps,
  type AdminApiError,
  type DepDownloadStatus,
  type DepStatus,
} from "@/lib/admin-api";
import {
  useModelsData,
  type AdminModelItem,
  type AdminModelProviderType,
  type AdminModelRuntimeState,
  type AdminPendingItem,
} from "@/hooks/use-models-data";

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
  url: "链接",
};
const providerTypeLabelMap: Record<AdminModelProviderType, string> = {
  trellis2: "TRELLIS2",
  hunyuan3d: "HunYuan3D-2",
  step1x3d: "Step1X-3D",
};

function formatSpeedBps(bps: number): string {
  if (bps <= 0) return "";
  const mbps = bps / (1024 * 1024);
  return `${mbps.toFixed(1)} MB/s`;
}

function clampProgress(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function formatProgress(value: number): string {
  return `${Math.round(clampProgress(value))}%`;
}

function getDependencyLabel(dep: DepStatus, fallback: string): string {
  const description = String(dep.description || "").trim();
  if (description) return description;
  const depId = String(dep.dep_id || "").trim();
  if (depId) return depId;
  const hfRepoId = String(dep.hf_repo_id || "").trim();
  if (hfRepoId) return hfRepoId;
  return fallback;
}

function getDependencyKey(dep: DepStatus, index: number): string {
  const depId = String(dep.dep_id || "").trim();
  const hfRepoId = String(dep.hf_repo_id || "").trim();
  return `${depId || "dep"}:${hfRepoId || "repo"}:${index}`;
}

function DownloadStageRow({
  label,
  status,
  progress,
  speedBps,
  errorText,
}: {
  label: string;
  status: DepDownloadStatus;
  progress: number;
  speedBps: number;
  errorText?: string;
}) {
  const { t } = useTranslation();
  const speed = formatSpeedBps(speedBps);
  const normalizedProgress = status === "done" ? 100 : clampProgress(progress);
  const progressText = formatProgress(normalizedProgress);
  const normalizedErrorText = String(errorText || "").trim();

  if (status === "downloading" || status === "done") {
    return (
      <div className="flex items-center gap-2">
        <span className="w-36 shrink-0 text-xs text-text-secondary">[{label}]</span>
        <Progress className="flex-1" value={normalizedProgress} />
        <span className="w-12 shrink-0 text-right text-xs text-text-secondary">{progressText}</span>
        <span className="w-20 shrink-0 text-right text-xs text-text-secondary">
          {status === "done" ? t("models.pending.stage.completed") : (speed || "—")}
        </span>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex items-center gap-2">
        <span className="w-36 shrink-0 text-xs text-text-secondary">[{label}]</span>
        <span className="text-xs text-danger-text">
          {normalizedErrorText || t("models.pending.stage.error")}
        </span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="w-36 shrink-0 text-xs text-text-secondary">[{label}]</span>
      <span className="text-xs text-text-muted">{t("models.pending.stage.waiting")}</span>
    </div>
  );
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
  const isMainDownloadComplete = item.downloadStatus === "downloading"
    && clampProgress(item.downloadProgress) >= 100;
  const mainStageStatus: DepDownloadStatus = isMainDownloadComplete ? "done" : item.downloadStatus;
  const canCancel = item.downloadStatus !== "error";
  const normalizedDownloadError = String(item.downloadError || "").trim();

  return (
    <div className="grid gap-2 rounded-xl border border-outline bg-surface-container-lowest p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="grid gap-0.5">
          <span className="text-sm font-semibold text-text-primary">
            {item.downloadStatus === "error"
              ? t("models.pending.failedWithName", { name: item.displayName })
              : t("models.pending.downloadingWithName", { name: item.displayName })}
          </span>
          <span
            className="max-w-[320px] truncate text-xs text-text-secondary"
            title={item.modelPath}
          >
            {item.modelPath}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {canCancel ? (
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
                title={t("models.pending.retry")}
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                size="sm"
                variant="danger"
                onClick={() => onRemove(item.id)}
                title={t("models.pending.remove")}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="grid gap-1.5">
        <DownloadStageRow
          label={t("models.pending.stage.mainModel")}
          status={mainStageStatus}
          progress={mainStageStatus === "done" ? 100 : item.downloadProgress}
          speedBps={mainStageStatus === "done" ? 0 : item.downloadSpeedBps}
          errorText={item.downloadError}
        />
        {item.deps.map((dep, index) => (
          <DownloadStageRow
            key={getDependencyKey(dep, index)}
            label={getDependencyLabel(dep, t("models.pending.stage.depFallback"))}
            status={dep.download_status}
            progress={dep.download_status === "done" ? 100 : dep.download_progress}
            speedBps={dep.download_speed_bps}
            errorText={dep.download_error}
          />
        ))}
      </div>

      {item.downloadStatus === "error" && normalizedDownloadError ? (
        <p className="text-xs text-danger-text">{normalizedDownloadError}</p>
      ) : null}
    </div>
  );
}

function DependencyDetailStatus({ dep }: { dep: DepStatus }) {
  const { t } = useTranslation();
  const speed = formatSpeedBps(dep.download_speed_bps);
  const progress = dep.download_status === "done"
    ? 100
    : clampProgress(dep.download_progress);
  const progressText = formatProgress(progress);
  const downloadError = String(dep.download_error || "").trim();

  if (dep.download_status === "done") {
    return (
      <div className="inline-flex items-center gap-1.5 text-xs text-success-text">
        <span className="h-2 w-2 rounded-full bg-success-text" />
        <span>{t("models.details.dependencies.ready")}</span>
      </div>
    );
  }

  if (dep.download_status === "downloading") {
    return (
      <div className="grid gap-1">
        <Progress value={progress} />
        <div className="flex items-center justify-between text-xs text-text-secondary">
          <span>{progressText}</span>
          <span>{speed || "—"}</span>
        </div>
      </div>
    );
  }

  if (dep.download_status === "error") {
    return (
      <p className="text-xs text-danger-text">
        {downloadError || t("models.details.dependencies.error")}
      </p>
    );
  }

  return (
    <div className="inline-flex items-center gap-1.5 text-xs text-text-muted">
      <span className="h-2 w-2 rounded-full bg-text-muted" />
      <span>{t("models.details.dependencies.waiting")}</span>
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
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [deleteTargetId, setDeleteTargetId] = useState("");
  const [detailModel, setDetailModel] = useState<AdminModelItem | null>(null);
  const [detailDeps, setDetailDeps] = useState<DepStatus[]>([]);
  const [detailDepsLoading, setDetailDepsLoading] = useState(false);
  const [detailDepsError, setDetailDepsError] = useState("");
  const detailDepsRequestIdRef = useRef(0);

  const runModelAction = useCallback(async (action: () => Promise<void>) => {
    try {
      await action();
    } catch (modelActionError) {
      toast.error(modelActionError instanceof Error ? modelActionError.message : String(modelActionError));
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

  const handleDeleteRequest = useCallback((id: string) => {
    setDeleteTargetId(id);
  }, []);

  const handleDeleteCancel = useCallback(() => {
    setDeleteTargetId("");
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    const id = deleteTargetId;
    setDeleteTargetId("");
    try {
      await removeModel(id);
    } catch (err) {
      const apiErr = err as AdminApiError;
      if (apiErr.status === 400) {
        toast.error(t("models.list.deleteLastError"));
      } else {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    }
  }, [deleteTargetId, removeModel, t]);

  const handleStartDownload = useCallback((item: AdminPendingItem) => {
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

  const handleOpenDetails = useCallback((model: AdminModelItem) => {
    const requestId = detailDepsRequestIdRef.current + 1;
    detailDepsRequestIdRef.current = requestId;
    setDetailModel(model);
    setDetailDeps([]);
    setDetailDepsError("");
    setDetailDepsLoading(true);

    fetchModelDeps(model.id)
      .then((deps) => {
        if (detailDepsRequestIdRef.current !== requestId) return;
        setDetailDeps(deps);
      })
      .catch((depsError) => {
        if (detailDepsRequestIdRef.current !== requestId) return;
        setDetailDepsError(depsError instanceof Error ? depsError.message : String(depsError));
      })
      .finally(() => {
        if (detailDepsRequestIdRef.current !== requestId) return;
        setDetailDepsLoading(false);
      });
  }, []);

  const handleDetailDialogOpenChange = useCallback((open: boolean) => {
    if (!open) {
      detailDepsRequestIdRef.current += 1;
      setDetailModel(null);
      setDetailDeps([]);
      setDetailDepsError("");
      setDetailDepsLoading(false);
    }
  }, []);

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error) return <div className="flex items-center justify-center h-full text-red-500">{error}</div>;

  const hasPending = pendingItems.length > 0;
  const deleteTargetModel = models.find((m) => m.id === deleteTargetId) ?? null;
  const defaultPendingItem = pendingItems.find((item) => item.isDefault) ?? null;
  const detailProviderLabel = detailModel
    ? providerTypeLabelMap[detailModel.providerType] ?? detailModel.providerType
    : "";
  const detailSourceLabel = detailModel
    ? sourceLabelMap[detailModel.weightSource] ?? detailModel.weightSource
    : "";
  const detailResolvedPath = detailModel
    ? (detailModel.resolvedPath || detailModel.modelPath)
    : "";
  const shouldShowDepsBlock = !detailDepsLoading && detailDeps.length > 0;

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
              <col className="w-[30%]" />
              <col className="w-[10%]" />
              <col className="w-[8%]" />
              <col className="w-[52%]" />
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
                  <td colSpan={4}>
                    <FirstRunWizard
                      defaultPendingItem={defaultPendingItem}
                      onStartDownload={handleStartDownload}
                    />
                  </td>
                </tr>
              ) : models.map((model) => {
                const isBusy = busyModelId === model.id;
                const runtimeErrorTooltip = model.runtimeState === "error" && model.errorMessage
                  ? model.errorMessage
                  : undefined;
                return (
                  <tr key={model.id}>
                    <td className={tableCellLeftClassName}>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <div className="text-sm font-semibold text-text-primary">{model.displayName}</div>
                        {model.isDefault ? (
                          <Badge tone="accent">{t("models.list.defaultTag")}</Badge>
                        ) : null}
                      </div>
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
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => handleOpenDetails(model)}
                        >
                          {t("models.list.details")}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="danger"
                          disabled={isBusy || models.length === 1}
                          onClick={() => handleDeleteRequest(model.id)}
                          title={t("models.list.delete")}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

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

      <Dialog open={Boolean(detailModel)} onOpenChange={handleDetailDialogOpenChange}>
        <DialogContent className="w-[min(92vw,720px)] p-4">
          <DialogHeader className="pr-8">
            <DialogTitle>{t("models.details.title")}</DialogTitle>
            <DialogDescription>
              {t("models.details.description", { name: detailModel?.displayName || "" })}
            </DialogDescription>
          </DialogHeader>
          {detailModel ? (
            <div className="grid gap-3">
              <div className="grid gap-1.5 rounded-xl border border-outline bg-surface-container-lowest p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs text-text-muted">{t("models.details.fields.provider")}</span>
                  <span className="text-sm font-medium text-text-primary">{detailProviderLabel}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs text-text-muted">{t("models.details.fields.source")}</span>
                  <span className="text-sm font-medium text-text-primary">{detailSourceLabel}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs text-text-muted">{t("models.details.fields.runtime")}</span>
                  <Badge tone={runtimeToneMap[detailModel.runtimeState]}>
                    {t(`models.runtime.${detailModel.runtimeState}`)}
                  </Badge>
                </div>
                {detailResolvedPath ? (
                  <div className="grid gap-0.5">
                    <span className="text-xs text-text-muted">{t("models.details.fields.path")}</span>
                    <p className="break-all text-xs text-text-secondary">{detailResolvedPath}</p>
                  </div>
                ) : null}
              </div>

              {detailDepsLoading ? (
                <p className="text-xs text-text-secondary">
                  {t("models.details.dependenciesLoading")}
                </p>
              ) : null}

              {detailDepsError ? (
                <p className="text-xs text-danger-text">
                  {t("models.details.dependenciesLoadFailed", { message: detailDepsError })}
                </p>
              ) : null}

              {shouldShowDepsBlock ? (
                <div className="grid gap-2 rounded-xl border border-outline bg-surface-container-lowest p-3">
                  <h3 className="text-sm font-semibold text-text-primary">
                    {t("models.details.dependencies.title")}
                  </h3>
                  <div className="grid gap-2">
                    {detailDeps.map((dep, index) => (
                      <div
                        key={getDependencyKey(dep, index)}
                        className="grid gap-1 rounded-lg border border-outline bg-surface-container p-2.5"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold text-text-primary">
                            {getDependencyLabel(dep, t("models.details.dependencies.depFallback"))}
                          </span>
                          <span className="text-xs text-text-secondary">{dep.hf_repo_id}</span>
                        </div>
                        {dep.resolved_path ? (
                          <p className="break-all text-xs text-text-secondary">{dep.resolved_path}</p>
                        ) : null}
                        <DependencyDetailStatus dep={dep} />
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTargetModel)} onOpenChange={(open) => { if (!open) handleDeleteCancel(); }}>
        <DialogContent className="w-[min(92vw,420px)] p-4">
          <DialogHeader className="pr-8">
            <DialogTitle>{t("models.list.deleteConfirmTitle")}</DialogTitle>
            <DialogDescription>
              {t("models.list.deleteConfirmDescription", { name: deleteTargetModel?.displayName ?? "" })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" size="sm" variant="outline" onClick={handleDeleteCancel}>
              {t("models.addModel.cancel")}
            </Button>
            <Button type="button" size="sm" variant="danger" onClick={handleDeleteConfirm}>
              {t("models.list.deleteConfirmOk")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AddModelDialog
        open={addDialogOpen}
        onOpenChange={setAddDialogOpen}
        onSubmit={handleAddModel}
      />
    </div>
  );
}
