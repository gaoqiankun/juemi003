import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SettingField, SettingsData } from "@/data/admin-mocks";
import { Button, Card, SelectField, TextField, ToggleSwitch } from "@/components/ui/primitives";
import { useSettingsData } from "@/hooks/use-settings-data";
import {
  connectHf,
  disconnectHf,
  fetchHfStatus,
  updateHfEndpoint,
  updateSettings,
  type HfStatusResponse,
} from "@/lib/admin-api";

type SettingValue = boolean | number | string;
const DEFAULT_HF_ENDPOINT = "https://huggingface.co";

const UPDATABLE_SETTING_KEYS = new Set([
  "defaultProvider",
  "queueMaxSize",
  "rateLimitPerHour",
  "rateLimitConcurrent",
]);

function normalizeSettings(source: SettingsData): SettingsData {
  return {
    sections: source.sections.map((section) => ({
      ...section,
      fields: section.fields.map((field) => {
        if (field.type !== "select") {
          return { ...field };
        }
        const options = field.options || [];
        const currentValue = typeof field.value === "string" ? field.value : "";
        const fallbackValue = options[0]?.value || "";
        return {
          ...field,
          value: currentValue || fallbackValue,
        };
      }),
    })),
  };
}

function extractPayload(data: SettingsData | null): Record<string, SettingValue> {
  if (!data) {
    return {};
  }
  const payload: Record<string, SettingValue> = {};
  for (const section of data.sections) {
    for (const field of section.fields) {
      if (UPDATABLE_SETTING_KEYS.has(field.key)) {
        payload[field.key] = field.value as SettingValue;
      }
    }
  }
  return payload;
}

function payloadFingerprint(payload: Record<string, SettingValue>) {
  return JSON.stringify(payload);
}

function isFieldReadonly(field: SettingField) {
  return Boolean((field as { readonly?: boolean }).readonly);
}

export function SettingsPage() {
  const { t } = useTranslation();
  const { data: source, loading, error } = useSettingsData();
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [baselineFingerprint, setBaselineFingerprint] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveSuccess, setSaveSuccess] = useState("");
  const [hfStatus, setHfStatus] = useState<HfStatusResponse | null>(null);
  const [hfLoading, setHfLoading] = useState(true);
  const [hfBusy, setHfBusy] = useState(false);
  const [hfEndpointBusy, setHfEndpointBusy] = useState(false);
  const [hfEndpoint, setHfEndpoint] = useState(DEFAULT_HF_ENDPOINT);
  const [hfToken, setHfToken] = useState("");
  const [hfError, setHfError] = useState("");
  const [hfSuccess, setHfSuccess] = useState("");

  useEffect(() => {
    if (source) {
      const normalizedSettings = normalizeSettings(source);
      setSettings(normalizedSettings);
      setBaselineFingerprint(payloadFingerprint(extractPayload(normalizedSettings)));
      setSaveError("");
      setSaveSuccess("");
    }
  }, [source]);

  const refreshHfStatus = useCallback(async () => {
    setHfLoading(true);
    try {
      const status = await fetchHfStatus();
      setHfStatus(status);
      setHfEndpoint(status.endpoint || DEFAULT_HF_ENDPOINT);
      setHfError("");
    } catch (hfStatusError) {
      setHfError(hfStatusError instanceof Error ? hfStatusError.message : String(hfStatusError));
      setHfStatus(null);
      setHfEndpoint(DEFAULT_HF_ENDPOINT);
    } finally {
      setHfLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshHfStatus().catch(() => undefined);
  }, [refreshHfStatus]);

  const currentPayload = useMemo(() => extractPayload(settings), [settings]);
  const currentFingerprint = useMemo(
    () => payloadFingerprint(currentPayload),
    [currentPayload],
  );
  const hasChanges = currentFingerprint !== baselineFingerprint;

  const updateField = useCallback((sectionKey: string, fieldKey: string, value: SettingValue) => {
    setSettings((current) => {
      if (!current) return current;
      return {
        sections: current.sections.map((section) => (
          section.key !== sectionKey
            ? section
            : {
              ...section,
              fields: section.fields.map((field) => (
                field.key === fieldKey ? { ...field, value } : field
              )),
            }
        )),
      };
    });
    setSaveSuccess("");
  }, []);

  const handleSave = useCallback(async () => {
    if (!settings || isSaving || !hasChanges) {
      return;
    }
    setIsSaving(true);
    setSaveError("");
    setSaveSuccess("");
    try {
      await updateSettings(currentPayload);
      setBaselineFingerprint(currentFingerprint);
      setSaveSuccess(t("settings.save.success"));
    } catch (saveRequestError) {
      setSaveError(saveRequestError instanceof Error ? saveRequestError.message : String(saveRequestError));
    } finally {
      setIsSaving(false);
    }
  }, [currentFingerprint, currentPayload, hasChanges, isSaving, settings, t]);

  const handleHfConnect = useCallback(async () => {
    if (hfBusy || hfLoading || hfEndpointBusy) {
      return;
    }
    const token = hfToken.trim();
    if (!token) {
      setHfError(t("settings.hf.tokenRequired"));
      return;
    }
    setHfBusy(true);
    setHfError("");
    setHfSuccess("");
    try {
      const status = await connectHf(token);
      setHfStatus(status);
      setHfToken("");
      setHfSuccess(t("settings.hf.connectSuccess"));
    } catch (hfConnectError) {
      setHfError(hfConnectError instanceof Error ? hfConnectError.message : String(hfConnectError));
    } finally {
      setHfBusy(false);
    }
  }, [hfBusy, hfEndpointBusy, hfLoading, hfToken, t]);

  const handleHfDisconnect = useCallback(async () => {
    if (hfBusy || hfLoading || hfEndpointBusy) {
      return;
    }
    setHfBusy(true);
    setHfError("");
    setHfSuccess("");
    try {
      const status = await disconnectHf();
      setHfStatus(status);
      setHfSuccess(t("settings.hf.disconnectSuccess"));
    } catch (hfDisconnectError) {
      setHfError(hfDisconnectError instanceof Error ? hfDisconnectError.message : String(hfDisconnectError));
    } finally {
      setHfBusy(false);
    }
  }, [hfBusy, hfEndpointBusy, hfLoading, t]);

  const handleHfEndpointSave = useCallback(async () => {
    if (hfBusy || hfLoading || hfEndpointBusy) {
      return;
    }
    setHfEndpointBusy(true);
    setHfError("");
    setHfSuccess("");
    try {
      const result = await updateHfEndpoint(hfEndpoint);
      const nextEndpoint = result.endpoint || DEFAULT_HF_ENDPOINT;
      setHfEndpoint(nextEndpoint);
      setHfStatus((current) => (
        current ? { ...current, endpoint: nextEndpoint } : current
      ));
      setHfSuccess(t("settings.hf.endpointSaveSuccess"));
    } catch (hfEndpointError) {
      setHfError(hfEndpointError instanceof Error ? hfEndpointError.message : String(hfEndpointError));
    } finally {
      setHfEndpointBusy(false);
    }
  }, [hfBusy, hfEndpoint, hfEndpointBusy, hfLoading, t]);

  const normalizedEndpointInput = hfEndpoint.trim() || DEFAULT_HF_ENDPOINT;
  const persistedEndpoint = (hfStatus?.endpoint || DEFAULT_HF_ENDPOINT).trim() || DEFAULT_HF_ENDPOINT;
  const hasEndpointChanges = normalizedEndpointInput !== persistedEndpoint;
  const hfStatusBadge = hfLoading
    ? {
      className: "inline-flex items-center rounded-full bg-surface-container-low px-2 py-0.5 text-xs font-medium text-text-muted",
      text: "...",
    }
    : hfStatus?.logged_in
      ? {
        className: "inline-flex items-center rounded-full bg-success/10 px-2 py-0.5 text-xs font-medium text-success-text",
        text: String(hfStatus.username || "").trim() || t("settings.hf.connected"),
      }
      : {
        className: "inline-flex items-center rounded-full bg-surface-container-low px-2 py-0.5 text-xs font-medium text-text-muted",
        text: t("settings.hf.notConnected"),
      };

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error || !settings) return <div className="flex items-center justify-center h-full text-red-500">{error || "Failed to load"}</div>;

  return (
    <div className="grid gap-4">
      <section className="grid gap-4">
        {settings.sections.map((section) => (
          <Card key={section.key} className="grid gap-3 p-4">
            <h2 className="text-lg font-semibold tracking-[-0.02em] text-text-primary">
              {t(section.titleKey)}
            </h2>

            <div className="grid grid-cols-3 gap-3">
              {section.fields.map((field) => {
                const readonly = isFieldReadonly(field);
                const fallbackSuffixKey = field.key === "rateLimitPerHour"
                  ? "settings.suffix.perHour"
                  : field.key === "rateLimitConcurrent"
                    ? "settings.suffix.count"
                    : "";
                const suffixText = field.suffixKey
                  ? t(field.suffixKey)
                  : fallbackSuffixKey
                    ? t(fallbackSuffixKey)
                    : field.suffix;
                const fieldClassName = field.type === "text"
                  ? "grid col-span-3 gap-1.5 rounded-lg border border-outline bg-surface-container-low p-3"
                  : "grid gap-1.5 rounded-lg border border-outline bg-surface-container-low p-3";
                return (
                  <div key={field.key} className={fieldClassName}>
                    <div className="flex items-start justify-between gap-4">
                      {field.type === "toggle" ? (
                        <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                          {t(field.labelKey)}
                        </span>
                      ) : (
                        <label
                          className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted"
                          htmlFor={field.key}
                        >
                          {t(field.labelKey)}
                        </label>
                      )}

                      {field.type === "toggle" ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-medium text-text-secondary">
                            {t(Boolean(field.value) ? "common.status.active" : "common.status.paused")}
                          </span>
                          <ToggleSwitch
                            checked={Boolean(field.value)}
                            onChange={(nextValue) => updateField(section.key, field.key, nextValue)}
                            label={t(field.labelKey)}
                          />
                        </div>
                      ) : null}
                    </div>

                    {field.type === "text" ? (
                      <TextField
                        id={field.key}
                        value={String(field.value ?? "")}
                        disabled={readonly}
                        onChange={(event) => updateField(section.key, field.key, event.target.value)}
                      />
                    ) : null}

                    {field.type === "number" ? (
                      <div className="relative">
                        <TextField
                          id={field.key}
                          type="number"
                          value={String(field.value ?? "")}
                          disabled={readonly}
                          onChange={(event) => updateField(section.key, field.key, Number(event.target.value))}
                          className={suffixText ? "pr-16" : undefined}
                        />
                        {suffixText ? (
                          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-text-muted">
                            {suffixText}
                          </span>
                        ) : null}
                      </div>
                    ) : null}

                    {field.type === "select" ? (
                      <SelectField
                        value={typeof field.value === "string" ? field.value : ""}
                        onValueChange={(value) => updateField(section.key, field.key, value)}
                        options={(field.options || []).map((option) => ({
                          label: option.labelKey ? t(option.labelKey) : (option.label || option.value),
                          value: option.value,
                        }))}
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>

            {section.key === "generation" ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  disabled={!hasChanges || isSaving}
                  onClick={handleSave}
                >
                  {isSaving ? t("settings.save.saving") : t("common.saveChanges")}
                </Button>
                {saveSuccess ? <p className="text-sm text-success-text">{saveSuccess}</p> : null}
                {saveError ? <p className="text-sm text-danger-text">{saveError}</p> : null}
              </div>
            ) : null}
          </Card>
        ))}
      </section>

      <section>
        <Card tone="low" className="grid gap-3 p-4">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold tracking-[-0.02em] text-text-primary">
              {t("settings.hf.title")}
            </h2>
            <span className={hfStatusBadge.className}>{hfStatusBadge.text}</span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1.5 text-sm text-text-secondary" htmlFor="settings-hf-endpoint">
              <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                {t("settings.hf.endpointLabel")}
              </span>
              <TextField
                id="settings-hf-endpoint"
                type="text"
                value={hfEndpoint}
                placeholder={t("settings.hf.endpointPlaceholder")}
                onChange={(event) => setHfEndpoint(event.target.value)}
                disabled={hfLoading || hfEndpointBusy || hfBusy}
              />
            </label>

            <label className="grid gap-1.5 text-sm text-text-secondary" htmlFor="settings-hf-token">
              <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                {t("settings.hf.tokenLabel")}
              </span>
              <TextField
                id="settings-hf-token"
                type="password"
                value={hfStatus?.logged_in ? "" : hfToken}
                autoComplete="off"
                placeholder={hfStatus?.logged_in ? t("settings.hf.connected") : t("settings.hf.tokenPlaceholder")}
                onChange={(event) => setHfToken(event.target.value)}
                disabled={hfBusy || hfEndpointBusy || hfLoading || Boolean(hfStatus?.logged_in)}
              />
            </label>
          </div>
          <p className="text-xs text-text-muted">{t("settings.hf.endpointHint")}</p>

          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              type="button"
              size="sm"
              disabled={hfLoading || hfBusy || hfEndpointBusy || !hasEndpointChanges}
              onClick={handleHfEndpointSave}
            >
              {hfEndpointBusy ? t("settings.hf.savingEndpoint") : t("settings.hf.saveEndpoint")}
            </Button>
            {hfStatus?.logged_in ? (
              <Button
                type="button"
                size="sm"
                disabled={hfBusy || hfLoading || hfEndpointBusy}
                onClick={handleHfDisconnect}
              >
                {hfBusy ? t("settings.hf.disconnecting") : t("settings.hf.disconnect")}
              </Button>
            ) : (
              <Button
                type="button"
                variant="primary"
                size="sm"
                disabled={hfBusy || hfLoading || hfEndpointBusy}
                onClick={handleHfConnect}
              >
                {hfBusy ? t("settings.hf.connecting") : t("settings.hf.connect")}
              </Button>
            )}
          </div>

          {hfSuccess ? <p className="text-sm text-success-text">{hfSuccess}</p> : null}
          {hfError ? <p className="text-sm text-danger-text">{hfError}</p> : null}
        </Card>
      </section>

    </div>
  );
}
