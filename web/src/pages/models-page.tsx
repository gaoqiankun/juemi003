import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, ToggleSwitch } from "@/components/ui/primitives";
import { useModelsData, type AdminModelItem } from "@/hooks/use-models-data";

const tableHeadClassName = "px-4 pb-2 text-left font-display text-[11px] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableCellClassName = "bg-surface-container-lowest px-4 py-3 align-top text-sm text-text-secondary first:rounded-l-lg last:rounded-r-lg";

export function ModelsPage() {
  const { t } = useTranslation();
  const {
    models,
    loading,
    error,
    busyModelId,
    setModelEnabled,
    setModelDefault,
    removeModel,
  } = useModelsData();
  const [actionError, setActionError] = useState("");

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

  const handleDelete = useCallback((model: AdminModelItem) => {
    if (!window.confirm(t("models.list.confirmDelete", { name: model.displayName }))) {
      return;
    }
    runModelAction(() => removeModel(model.id));
  }, [removeModel, runModelAction, t]);

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error) return <div className="flex items-center justify-center h-full text-red-500">{error}</div>;

  return (
    <div className="grid gap-6">
      <Card className="grid gap-5 p-5">
        <h2 className="text-lg font-semibold tracking-[-0.03em] text-text-primary">{t("models.list.title")}</h2>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-separate border-spacing-y-2">
            <thead>
              <tr>
                <th className={tableHeadClassName}>{t("models.list.columns.name")}</th>
                <th className={tableHeadClassName}>{t("models.list.columns.status")}</th>
                <th className={tableHeadClassName}>{t("models.list.columns.default")}</th>
                <th className={tableHeadClassName}>{t("models.list.columns.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {models.length === 0 ? (
                <tr>
                  <td className={tableCellClassName} colSpan={4}>
                    {t("models.list.empty")}
                  </td>
                </tr>
              ) : models.map((model) => {
                const isBusy = busyModelId === model.id;
                return (
                  <tr key={model.id}>
                    <td className={tableCellClassName}>
                      <div className="text-sm font-semibold text-text-primary">{model.displayName}</div>
                      <div className="mt-1 font-mono text-xs text-text-muted">{model.id}</div>
                    </td>
                    <td className={tableCellClassName}>
                      <div className="flex items-center gap-3">
                        <ToggleSwitch
                          checked={model.isEnabled}
                          onChange={(nextValue) => handleToggleModel(model, nextValue)}
                          label={t("models.list.toggleLabel", { name: model.displayName })}
                          className="data-[state=checked]:bg-success-text"
                        />
                        <span className="text-sm text-text-secondary">
                          {t(model.isEnabled ? "models.list.enabled" : "models.list.disabled")}
                        </span>
                      </div>
                    </td>
                    <td className={tableCellClassName}>
                      {model.isDefault ? (
                        <Badge tone="accent">{t("models.list.defaultTag")}</Badge>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          disabled={isBusy}
                          onClick={() => handleSetDefault(model)}
                        >
                          {t("models.list.setDefault")}
                        </Button>
                      )}
                    </td>
                    <td className={tableCellClassName}>
                      <Button
                        type="button"
                        size="sm"
                        variant="danger"
                        disabled={isBusy}
                        onClick={() => handleDelete(model)}
                      >
                        {t("models.list.delete")}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {busyModelId ? <p className="text-sm text-text-secondary">{t("models.list.saving")}</p> : null}
        {actionError ? <p className="text-sm text-danger-text">{actionError}</p> : null}
      </Card>
    </div>
  );
}
