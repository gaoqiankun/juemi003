import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SettingsData } from "@/data/admin-mocks";
import { Button, Card, SelectField, TextField, ToggleSwitch } from "@/components/ui/primitives";
import { useSettingsData } from "@/hooks/use-settings-data";

export function SettingsPage() {
  const { t } = useTranslation();
  const { data: source, loading, error } = useSettingsData();
  const [settings, setSettings] = useState<SettingsData | null>(null);

  useEffect(() => {
    if (source) {
      setSettings(source);
    }
  }, [source]);

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-text-secondary">Loading...</span></div>;
  if (error || !settings) return <div className="flex items-center justify-center h-full text-red-500">{error || "Failed to load"}</div>;

  const updateField = (sectionKey: string, fieldKey: string, value: boolean | number | string) => {
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
  };

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-[-0.03em] text-text-primary">{t("settings.title")}</h2>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_20rem]">
        <div className="grid gap-4">
          {settings.sections.map((section) => (
            <Card key={section.key} className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                    {t(section.titleKey)}
                  </div>
                  <h3 className="mt-1 text-lg font-semibold tracking-[-0.02em] text-text-primary">
                    {t(section.descriptionKey)}
                  </h3>
                </div>
              </div>

              <div className="mt-4 grid gap-3">
                {section.fields.map((field) => (
                  <div key={field.key} className="grid gap-3 rounded-lg border border-outline bg-surface-container-low p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="grid gap-1">
                        <label
                          className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted"
                          htmlFor={field.key}
                        >
                          {t(field.labelKey)}
                        </label>
                        <p className="text-sm leading-6 text-text-secondary">{t(field.descriptionKey)}</p>
                      </div>
                      {field.type === "toggle" ? (
                        <ToggleSwitch
                          checked={Boolean(field.value)}
                          onChange={(nextValue) => updateField(section.key, field.key, nextValue)}
                          label={t(field.labelKey)}
                        />
                      ) : null}
                    </div>

                    {field.type === "text" ? (
                      <TextField
                        id={field.key}
                        value={String(field.value)}
                        onChange={(event) => updateField(section.key, field.key, event.target.value)}
                      />
                    ) : null}

                    {field.type === "number" ? (
                      <div className="relative">
                        <TextField
                          id={field.key}
                          type="number"
                          value={String(field.value)}
                          onChange={(event) => updateField(section.key, field.key, Number(event.target.value))}
                          className={field.suffix ? "pr-16" : undefined}
                        />
                        {field.suffix ? (
                          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-text-muted">
                            {field.suffix}
                          </span>
                        ) : null}
                      </div>
                    ) : null}

                    {field.type === "select" ? (
                      <SelectField
                        value={String(field.value)}
                        onValueChange={(value) => updateField(section.key, field.key, value)}
                        options={(field.options || []).map((option) => ({
                          label: t(option.labelKey),
                          value: option.value,
                        }))}
                      />
                    ) : null}
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>

        <Card tone="low" className="grid content-start gap-4 p-5">
          <div>
            <div className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
              {t("settings.preview.title")}
            </div>
            <h3 className="mt-1 text-lg font-semibold tracking-[-0.02em] text-text-primary">
              {t("settings.preview.copy")}
            </h3>
          </div>

          <div className="grid gap-3">
            <PreviewDetail label={t("settings.preview.cluster")} value={t("settings.preview.clusterValue")} />
            <PreviewDetail label={t("settings.preview.storage")} value={t("settings.preview.storageValue")} />
            <PreviewDetail label={t("settings.preview.traffic")} value={t("settings.preview.trafficValue")} />
          </div>

          <div className="flex flex-wrap gap-3">
            <Button variant="primary">{t("common.saveChanges")}</Button>
            <Button variant="secondary">{t("common.resetDefaults")}</Button>
          </div>
        </Card>
      </section>
    </div>
  );
}

function PreviewDetail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 rounded-lg border border-outline bg-surface-container p-4">
      <div className="text-sm text-text-secondary">{label}</div>
      <div className="text-sm font-semibold text-text-primary">{value}</div>
    </div>
  );
}
