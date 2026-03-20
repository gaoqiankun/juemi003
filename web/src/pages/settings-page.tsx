import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { SettingsData } from "@/data/admin-mocks";
import { Button, Card, SelectField, TextField, ToggleSwitch } from "@/components/ui/primitives";
import { useSettingsData } from "@/hooks/use-settings-data";

export function SettingsPage() {
  const { t } = useTranslation();
  const source = useSettingsData();
  const [settings, setSettings] = useState<SettingsData>(source);

  const updateField = (sectionKey: string, fieldKey: string, value: boolean | number | string) => {
    setSettings((current) => ({
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
    }));
  };

  return (
    <div className="page-stack">
      <section className="page-header">
        <div>
          <div className="eyebrow">{t("shell.nav.settings")}</div>
          <h2 className="page-title">{t("settings.title")}</h2>
        </div>
        <p className="page-description">{t("settings.description")}</p>
      </section>

      <section className="settings-grid">
        <div className="settings-sections">
          {settings.sections.map((section) => (
            <Card key={section.key}>
              <div className="section-header">
                <div>
                  <div className="eyebrow">{t(section.titleKey)}</div>
                  <h3 className="section-title">{t(section.descriptionKey)}</h3>
                </div>
              </div>

              <div className="form-grid">
                {section.fields.map((field) => (
                  <div key={field.key} className="form-field-card">
                    <div className="form-field-head">
                      <div>
                        <label className="field-label" htmlFor={field.key}>
                          {t(field.labelKey)}
                        </label>
                        <p className="field-description">{t(field.descriptionKey)}</p>
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
                      <div className="input-suffix-wrap">
                        <TextField
                          id={field.key}
                          type="number"
                          value={String(field.value)}
                          onChange={(event) => updateField(section.key, field.key, Number(event.target.value))}
                        />
                        {field.suffix ? <span className="input-suffix">{field.suffix}</span> : null}
                      </div>
                    ) : null}

                    {field.type === "select" ? (
                      <SelectField
                        id={field.key}
                        value={String(field.value)}
                        onChange={(event) => updateField(section.key, field.key, event.currentTarget.value)}
                      >
                        {field.options?.map((option) => (
                          <option key={option.value} value={option.value}>
                            {t(option.labelKey)}
                          </option>
                        ))}
                      </SelectField>
                    ) : null}
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>

        <Card tone="muted" className="settings-sidebar-card">
          <div className="section-header">
            <div>
              <div className="eyebrow">{t("settings.preview.title")}</div>
              <h3 className="section-title">{t("settings.preview.copy")}</h3>
            </div>
          </div>

          <div className="detail-grid">
            <PreviewDetail label={t("settings.preview.cluster")} value={t("settings.preview.clusterValue")} />
            <PreviewDetail label={t("settings.preview.storage")} value={t("settings.preview.storageValue")} />
            <PreviewDetail label={t("settings.preview.traffic")} value={t("settings.preview.trafficValue")} />
          </div>

          <div className="settings-actions">
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
    <div className="detail-item">
      <div className="detail-label">{label}</div>
      <div className="detail-value">{value}</div>
    </div>
  );
}
