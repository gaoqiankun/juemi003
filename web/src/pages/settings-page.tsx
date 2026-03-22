import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SettingField, SettingsData } from "@/data/admin-mocks";
import { Button, Card, SelectField, TextField, ToggleSwitch } from "@/components/ui/primitives";
import { useSettingsData } from "@/hooks/use-settings-data";
import { updateSettings } from "@/lib/admin-api";

type SettingValue = boolean | number | string;

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

  useEffect(() => {
    if (source) {
      const normalizedSettings = normalizeSettings(source);
      setSettings(normalizedSettings);
      setBaselineFingerprint(payloadFingerprint(extractPayload(normalizedSettings)));
      setSaveError("");
      setSaveSuccess("");
    }
  }, [source]);

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

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error || !settings) return <div className="flex items-center justify-center h-full text-red-500">{error || "Failed to load"}</div>;

  return (
    <div className="grid gap-6">
      <section className="grid gap-4">
        {settings.sections.map((section) => (
          <Card key={section.key} className="grid gap-4 p-5">
            <h2 className="text-lg font-semibold tracking-[-0.02em] text-text-primary">
              {t(section.titleKey)}
            </h2>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
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
                  ? "grid gap-2 rounded-lg border border-outline bg-surface-container-low p-3 md:col-span-2 xl:col-span-3"
                  : "grid gap-2 rounded-lg border border-outline bg-surface-container-low p-3";
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
                        <div className="flex items-center gap-2">
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
          </Card>
        ))}
      </section>

      <section className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="primary"
          disabled={!hasChanges || isSaving}
          onClick={handleSave}
        >
          {isSaving ? t("settings.save.saving") : t("common.saveChanges")}
        </Button>
        {saveSuccess ? <p className="text-sm text-success-text">{saveSuccess}</p> : null}
        {saveError ? <p className="text-sm text-danger-text">{saveError}</p> : null}
      </section>
    </div>
  );
}
