import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, ToggleSwitch } from "@/components/ui/primitives";
import { useModelsData, type AdminModelItem, type AdminModelRuntimeState } from "@/hooks/use-models-data";

const tableHeadBaseClassName = "px-4 pb-2 font-display text-[11px] font-semibold uppercase tracking-[0.05em] text-text-muted";
const tableHeadLeftClassName = `${tableHeadBaseClassName} text-left`;
const tableHeadCenterClassName = `${tableHeadBaseClassName} text-center`;
const tableCellBaseClassName = "bg-surface-container-lowest px-4 py-2.5 align-top text-sm text-text-secondary first:rounded-l-lg last:rounded-r-lg";
const tableCellLeftClassName = `${tableCellBaseClassName} text-left`;
const tableCellCenterClassName = `${tableCellBaseClassName} text-center`;

const runtimeToneMap: Record<AdminModelRuntimeState, "success" | "warning" | "danger" | "neutral"> = {
  ready: "success",
  loading: "warning",
  not_loaded: "neutral",
  error: "danger",
  unknown: "neutral",
};

export function ModelsPage() {
  const { t } = useTranslation();
  const {
    models,
    loading,
    error,
    busyModelId,
    setModelEnabled,
    setModelDefault,
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

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error) return <div className="flex items-center justify-center h-full text-red-500">{error}</div>;

  return (
    <div className="grid gap-6">
      <Card className="grid gap-5 p-5">
        <h2 className="text-lg font-semibold tracking-[-0.03em] text-text-primary">{t("models.list.title")}</h2>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] table-fixed border-separate border-spacing-y-2">
            <colgroup>
              <col className="w-[36%]" />
              <col className="w-[22%]" />
              <col className="w-[42%]" />
            </colgroup>
            <thead>
              <tr>
                <th className={tableHeadLeftClassName}>{t("models.list.columns.name")}</th>
                <th className={tableHeadCenterClassName}>{t("models.list.columns.runtime")}</th>
                <th className={tableHeadCenterClassName}>{t("models.list.columns.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {models.length === 0 ? (
                <tr>
                  <td className={tableCellLeftClassName} colSpan={3}>
                    {t("models.list.empty")}
                  </td>
                </tr>
              ) : models.map((model) => {
                const isBusy = busyModelId === model.id;
                return (
                  <tr key={model.id}>
                    <td className={tableCellLeftClassName}>
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="text-sm font-semibold text-text-primary">{model.displayName}</div>
                        {model.isDefault ? (
                          <Badge tone="accent">{t("models.list.defaultTag")}</Badge>
                        ) : null}
                      </div>
                    </td>
                    <td className={tableCellCenterClassName}>
                      <div className="grid justify-items-center gap-1.5">
                        <Badge tone={runtimeToneMap[model.runtimeState]}>
                          {t(`models.runtime.${model.runtimeState}`)}
                        </Badge>
                        {model.runtimeState === "error" && model.errorMessage ? (
                          <p className="max-w-xs rounded-md border border-danger/40 bg-danger/10 px-2 py-1 text-left text-xs leading-5 text-danger-text">
                            {model.errorMessage}
                          </p>
                        ) : null}
                      </div>
                    </td>
                    <td className={tableCellCenterClassName}>
                      <div className="flex items-center justify-center gap-2.5 whitespace-nowrap">
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

                        {!model.isDefault ? (
                          <Button
                            type="button"
                            size="sm"
                            disabled={isBusy}
                            className="h-7 px-2.5 text-xs font-medium"
                            onClick={() => handleSetDefault(model)}
                          >
                            {t("models.list.setDefault")}
                          </Button>
                        ) : null}
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
    </div>
  );
}
