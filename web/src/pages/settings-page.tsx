import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import type { SettingField } from "@/data/admin-mocks";
import { Button, Card, SelectField, TextField, ToggleSwitch } from "@/components/ui/primitives";
import { useSettingsData } from "@/hooks/use-settings-data";
import {
  cleanOrphans,
  connectHf,
  disconnectHf,
  fetchHfStatus,
  getStorageStats,
  updateHfEndpoint,
  updateSettings,
  type GpuDeviceSetting,
  type HfStatusResponse,
  type SettingsData,
  type StorageStats,
} from "@/lib/admin-api";

function formatBytes(bytes: number): string {
  return `${(bytes / (1024 ** 3)).toFixed(1)} GB`;
}

type SettingValue = boolean | number | string;
type SettingsPayloadValue = SettingValue | string[];
const DEFAULT_HF_ENDPOINT = "https://huggingface.co";

const UPDATABLE_SETTING_KEYS = new Set([
  "defaultProvider",
  "queueMaxSize",
  "maxLoadedModels",
  "maxTasksPerSlot",
  "rateLimitPerHour",
  "rateLimitConcurrent",
]);

function normalizeGpuDevices(devices: GpuDeviceSetting[] | undefined): GpuDeviceSetting[] {
  if (!Array.isArray(devices)) {
    return [];
  }
  return devices
    .map((device) => ({
      deviceId: String(device.deviceId || "").trim(),
      enabled: Boolean(device.enabled),
    }))
    .filter((device) => Boolean(device.deviceId));
}

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
    gpuDevices: normalizeGpuDevices(source.gpuDevices),
  };
}

function extractPayload(data: SettingsData | null): Record<string, SettingsPayloadValue> {
  if (!data) {
    return {};
  }
  const payload: Record<string, SettingsPayloadValue> = {};
  for (const section of data.sections) {
    for (const field of section.fields) {
      if (UPDATABLE_SETTING_KEYS.has(field.key)) {
        payload[field.key] = field.value as SettingValue;
      }
    }
  }
  payload.gpuDisabledDevices = data.gpuDevices
    ?.filter((device) => !device.enabled)
    .map((device) => device.deviceId)
    .sort() || [];
  return payload;
}

function payloadFingerprint(payload: Record<string, SettingsPayloadValue>) {
  return JSON.stringify(payload);
}

function isFieldReadonly(field: SettingField) {
  return Boolean((field as { readonly?: boolean }).readonly);
}

function findSettingField(data: SettingsData | null, fieldKey: string): SettingField | null {
  if (!data) {
    return null;
  }
  for (const section of data.sections) {
    for (const field of section.fields) {
      if (field.key === fieldKey) {
        return field;
      }
    }
  }
  return null;
}

function parseMaxLoadedModelsUpperBound(field: SettingField | null): number | null {
  const suffix = typeof field?.suffix === "string" ? field.suffix : "";
  const match = suffix.match(/<=\s*(\d+)/);
  if (!match) {
    return null;
  }
  const upperBound = Number.parseInt(match[1], 10);
  return Number.isFinite(upperBound) ? upperBound : null;
}

function validateMaxLoadedModels(settings: SettingsData | null): string {
  const field = findSettingField(settings, "maxLoadedModels");
  if (!field) {
    return "";
  }
  const value = typeof field.value === "number" ? field.value : Number(field.value);
  if (!Number.isInteger(value)) {
    return "maxLoadedModels must be an integer";
  }
  const upperBound = parseMaxLoadedModelsUpperBound(field);
  if (upperBound !== null && (value < 1 || value > upperBound)) {
    return `maxLoadedModels must be between 1 and ${upperBound}`;
  }
  if (value < 1) {
    return "maxLoadedModels must be >= 1";
  }
  return "";
}

function isMaxLoadedModelsError(errorMessage: string): boolean {
  return errorMessage.includes("maxLoadedModels");
}

export function SettingsPage() {
  const { t } = useTranslation();
  const { data: source, loading, error } = useSettingsData();
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [baselineFingerprint, setBaselineFingerprint] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [maxLoadedModelsError, setMaxLoadedModelsError] = useState("");
  const [hfStatus, setHfStatus] = useState<HfStatusResponse | null>(null);
  const [hfLoading, setHfLoading] = useState(true);
  const [hfBusy, setHfBusy] = useState(false);
  const [hfEndpointBusy, setHfEndpointBusy] = useState(false);
  const [hfEndpoint, setHfEndpoint] = useState(DEFAULT_HF_ENDPOINT);
  const [hfToken, setHfToken] = useState("");
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null);
  const [isCleaning, setIsCleaning] = useState(false);

  const refreshStorageStats = useCallback(async () => {
    try {
      const stats = await getStorageStats();
      setStorageStats(stats);
    } catch {
      // ignore — non-critical
    }
  }, []);

  const handleCleanOrphans = useCallback(async () => {
    if (isCleaning) return;
    setIsCleaning(true);
    try {
      const result = await cleanOrphans();
      toast.success(t("storage.cleaned", { freed: formatBytes(result.freed_bytes) }));
      await refreshStorageStats();
    } catch {
      // ignore
    } finally {
      setIsCleaning(false);
    }
  }, [isCleaning, refreshStorageStats, t]);

  useEffect(() => {
    refreshStorageStats().catch(() => undefined);
  }, [refreshStorageStats]);

  useEffect(() => {
    if (source) {
      const normalizedSettings = normalizeSettings(source);
      setSettings(normalizedSettings);
      setBaselineFingerprint(payloadFingerprint(extractPayload(normalizedSettings)));
      setMaxLoadedModelsError("");
    }
  }, [source]);

  useEffect(() => {
    if (!maxLoadedModelsError) {
      return;
    }
    setMaxLoadedModelsError(validateMaxLoadedModels(settings));
  }, [maxLoadedModelsError, settings]);

  const refreshHfStatus = useCallback(async () => {
    setHfLoading(true);
    try {
      const status = await fetchHfStatus();
      setHfStatus(status);
      setHfEndpoint(status.endpoint || DEFAULT_HF_ENDPOINT);
    } catch {
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
        ...current,
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
  }, []);

  const updateGpuDevice = useCallback((deviceId: string, enabled: boolean) => {
    setSettings((current) => {
      if (!current) return current;
      return {
        ...current,
        gpuDevices: current.gpuDevices?.map((device) => (
          device.deviceId === deviceId
            ? { ...device, enabled }
            : device
        )) || [],
      };
    });
  }, []);

  const handleSave = useCallback(async () => {
    if (!settings || isSaving || !hasChanges) {
      return;
    }
    const validationError = validateMaxLoadedModels(settings);
    if (validationError) {
      setMaxLoadedModelsError(validationError);
      toast.error(validationError);
      return;
    }

    setIsSaving(true);
    try {
      await updateSettings(currentPayload);
      setBaselineFingerprint(currentFingerprint);
      setMaxLoadedModelsError("");
      toast.success(t("settings.save.success"));
    } catch (saveRequestError) {
      const message = saveRequestError instanceof Error ? saveRequestError.message : String(saveRequestError);
      if (isMaxLoadedModelsError(message)) {
        setMaxLoadedModelsError(message);
      }
      toast.error(message);
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
      toast.error(t("settings.hf.tokenRequired"));
      return;
    }
    setHfBusy(true);
    try {
      const status = await connectHf(token);
      setHfStatus(status);
      setHfToken("");
      toast.success(t("settings.hf.connectSuccess"));
    } catch (hfConnectError) {
      toast.error(hfConnectError instanceof Error ? hfConnectError.message : String(hfConnectError));
    } finally {
      setHfBusy(false);
    }
  }, [hfBusy, hfEndpointBusy, hfLoading, hfToken, t]);

  const handleHfDisconnect = useCallback(async () => {
    if (hfBusy || hfLoading || hfEndpointBusy) {
      return;
    }
    setHfBusy(true);
    try {
      const status = await disconnectHf();
      setHfStatus(status);
      toast.success(t("settings.hf.disconnectSuccess"));
    } catch (hfDisconnectError) {
      toast.error(hfDisconnectError instanceof Error ? hfDisconnectError.message : String(hfDisconnectError));
    } finally {
      setHfBusy(false);
    }
  }, [hfBusy, hfEndpointBusy, hfLoading, t]);

  const handleHfEndpointSave = useCallback(async () => {
    if (hfBusy || hfLoading || hfEndpointBusy) {
      return;
    }
    setHfEndpointBusy(true);
    try {
      const result = await updateHfEndpoint(hfEndpoint);
      const nextEndpoint = result.endpoint || DEFAULT_HF_ENDPOINT;
      setHfEndpoint(nextEndpoint);
      setHfStatus((current) => (
        current ? { ...current, endpoint: nextEndpoint } : current
      ));
      toast.success(t("settings.hf.endpointSaveSuccess"));
    } catch (hfEndpointError) {
      toast.error(hfEndpointError instanceof Error ? hfEndpointError.message : String(hfEndpointError));
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
                  size="xs"
                  disabled={!hasChanges || isSaving || Boolean(maxLoadedModelsError)}
                  onClick={handleSave}
                >
                  {isSaving ? t("settings.save.saving") : t("common.saveChanges")}
                </Button>
              </div>
            ) : null}
          </Card>
        ))}
      </section>

      <section>
        <Card className="grid gap-3 p-4">
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-text-primary">
            {t("settings.gpuDevices.title")}
          </h2>

          <div className="grid gap-3">
            {settings.gpuDevices && settings.gpuDevices.length > 0 ? settings.gpuDevices.map((device) => (
              <div
                key={device.deviceId}
                className="grid gap-1.5 rounded-lg border border-outline bg-surface-container-low p-3"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="grid gap-1">
                    <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                      {t("settings.gpuDevices.device", { deviceId: device.deviceId })}
                    </span>
                    <span className="text-sm font-medium text-text-primary">
                      {device.deviceId}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-text-secondary">
                      {t(device.enabled ? "common.status.active" : "common.status.paused")}
                    </span>
                    <ToggleSwitch
                      checked={device.enabled}
                      onChange={(nextValue) => updateGpuDevice(device.deviceId, nextValue)}
                      label={t("settings.gpuDevices.device", { deviceId: device.deviceId })}
                    />
                  </div>
                </div>
              </div>
            )) : null}
          </div>
        </Card>
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
              size="xs"
              disabled={hfLoading || hfBusy || hfEndpointBusy || !hasEndpointChanges}
              onClick={handleHfEndpointSave}
            >
              {hfEndpointBusy ? t("settings.hf.savingEndpoint") : t("settings.hf.saveEndpoint")}
            </Button>
            {hfStatus?.logged_in ? (
              <Button
                type="button"
                size="xs"
                disabled={hfBusy || hfLoading || hfEndpointBusy}
                onClick={handleHfDisconnect}
              >
                {hfBusy ? t("settings.hf.disconnecting") : t("settings.hf.disconnect")}
              </Button>
            ) : (
              <Button
                type="button"
                variant="primary"
                size="xs"
                disabled={hfBusy || hfLoading || hfEndpointBusy}
                onClick={handleHfConnect}
              >
                {hfBusy ? t("settings.hf.connecting") : t("settings.hf.connect")}
              </Button>
            )}
          </div>

        </Card>
      </section>

      <section>
        <Card tone="low" className="grid gap-3 p-4">
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-text-primary">
            {t("storage.diskUsage")}
          </h2>

          {storageStats ? (
            <>
              <div className="grid gap-1.5">
                <div className="flex items-center justify-between text-xs text-text-secondary">
                  <span>{formatBytes(storageStats.disk_total_bytes - storageStats.disk_free_bytes)} / {formatBytes(storageStats.disk_total_bytes)}</span>
                  <span>{Math.round(((storageStats.disk_total_bytes - storageStats.disk_free_bytes) / storageStats.disk_total_bytes) * 100)}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-container-highest">
                  <div
                    className="h-full rounded-full bg-primary transition-all"
                    style={{ width: `${Math.min(100, ((storageStats.disk_total_bytes - storageStats.disk_free_bytes) / storageStats.disk_total_bytes) * 100).toFixed(1)}%` }}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1 rounded-lg border border-outline bg-surface-container-low p-3">
                  <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                    {t("storage.cache")}
                  </span>
                  <span className="text-sm font-medium text-text-primary">{formatBytes(storageStats.cache_bytes)}</span>
                </div>
                <div className="grid gap-1 rounded-lg border border-outline bg-surface-container-low p-3">
                  <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                    {t("storage.orphaned")}
                  </span>
                  <span className="text-sm font-medium text-text-primary">{formatBytes(storageStats.orphan_bytes)}</span>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                <Button
                  type="button"
                  size="xs"
                  disabled={isCleaning}
                  onClick={handleCleanOrphans}
                >
                  {isCleaning ? t("storage.cleaning") : t("storage.cleanOrphans")}
                </Button>
              </div>
            </>
          ) : (
            <p className="text-sm text-text-muted">...</p>
          )}
        </Card>
      </section>

    </div>
  );
}
