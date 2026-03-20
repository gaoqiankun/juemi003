import { useState } from "react";
import { ArrowUpRight, ImagePlus, LoaderCircle, Sparkles, Wand2 } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { GenerationRecord } from "@/data/user-mocks";
import { Button, Card, MeterBar, SelectField, StatusDot, TextField } from "@/components/ui/primitives";
import { useGenerateData } from "@/hooks/use-generate-data";
import { formatTimestamp } from "@/lib/admin-format";

export function GeneratePage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en";
  const { qualityOptions, formatOptions, featuredTask, progressSteps } = useGenerateData();
  const promptPreset = t("user.generate.promptPreset");
  const [prompt, setPrompt] = useState("");
  const [promptMode, setPromptMode] = useState<"preset" | "custom">("preset");
  const [quality, setQuality] = useState<GenerationRecord["quality"]>("production");
  const [format, setFormat] = useState<GenerationRecord["format"]>("glb");
  const [seed, setSeed] = useState("20814");
  const [sourceMode, setSourceMode] = useState<"sample" | "uploaded">("sample");

  return (
    <div className="page-stack">
      <section className="page-header">
        <div>
          <div className="eyebrow">{t("user.shell.nav.generate")}</div>
          <h2 className="page-title">{t("user.generate.title")}</h2>
        </div>
        <p className="page-description">{t("user.generate.description")}</p>
      </section>

      <section className="generate-grid">
        <Card className="generate-form-card">
          <div className="section-header">
            <div>
              <div className="eyebrow">{t("user.generate.uploadLabel")}</div>
              <h3 className="section-title">{t("user.generate.uploadTitle")}</h3>
            </div>
          </div>

          <button
            type="button"
            className="upload-surface"
            onClick={() => setSourceMode("uploaded")}
          >
            <div className="upload-icon-shell">
              <ImagePlus className="section-icon" />
            </div>
            <div>
              <div className="section-title">{t("user.generate.dropTitle")}</div>
              <p className="section-description">
                {sourceMode === "sample"
                  ? t("user.generate.sampleFile")
                  : t("user.generate.mockUploadReady")}
              </p>
            </div>
          </button>

          <div className="form-stack">
            <div className="form-field-card">
              <div className="field-label-row">
                <label className="field-label" htmlFor="generation-prompt">{t("user.generate.promptLabel")}</label>
                <span className="eyebrow">0/500</span>
              </div>
              <textarea
                id="generation-prompt"
                className="admin-input textarea-field"
                value={promptMode === "preset" ? promptPreset : prompt}
                onChange={(event) => {
                  setPromptMode("custom");
                  setPrompt(event.target.value);
                }}
                placeholder={t("user.generate.promptPlaceholder")}
              />
            </div>

            <div className="parameter-grid">
              <div className="form-field-card">
                <label className="field-label" htmlFor="generation-quality">{t("user.generate.qualityLabel")}</label>
                <SelectField
                  id="generation-quality"
                  value={quality}
                  onChange={(event) => setQuality(event.currentTarget.value as GenerationRecord["quality"])}
                >
                  {qualityOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </option>
                  ))}
                </SelectField>
              </div>

              <div className="form-field-card">
                <label className="field-label" htmlFor="generation-format">{t("user.generate.formatLabel")}</label>
                <SelectField
                  id="generation-format"
                  value={format}
                  onChange={(event) => setFormat(event.currentTarget.value as GenerationRecord["format"])}
                >
                  {formatOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </option>
                  ))}
                </SelectField>
              </div>

              <div className="form-field-card">
                <label className="field-label" htmlFor="generation-seed">{t("user.generate.seedLabel")}</label>
                <TextField
                  id="generation-seed"
                  value={seed}
                  onChange={(event) => setSeed(event.target.value)}
                />
              </div>
            </div>
          </div>

          <div className="button-row">
            <Button
              variant="secondary"
              onClick={() => {
                setPromptMode("preset");
                setPrompt("");
              }}
            >
              {t("user.generate.usePreset")}
            </Button>
            <Button variant="primary">
              {t("user.generate.createButton")}
              <Sparkles className="button-icon" />
            </Button>
          </div>
        </Card>

        <div className="generate-side-column">
          <Card tone="muted">
            <div className="section-header">
              <div>
                <div className="eyebrow">{t("user.generate.progressLabel")}</div>
                <h3 className="section-title">{t("user.generate.progressTitle")}</h3>
              </div>
              <StatusDot tone="accent" label={t("user.status.processing")} />
            </div>

            <div className="progress-step-list">
              {progressSteps.map((step) => (
                <div key={step.key} className="progress-step">
                  <div className="meter-meta">
                    <span>{t(step.key)}</span>
                    <span className="numeric">{step.progress}%</span>
                  </div>
                  <MeterBar value={step.progress} />
                </div>
              ))}
            </div>

            <div className="detail-item">
              <div className="detail-label">
                <LoaderCircle className="detail-icon" />
                <span>{t("user.generate.activeTaskLabel")}</span>
              </div>
              <div className="detail-value mono">gen_8de14a11</div>
            </div>
          </Card>

          <Card>
            <div className="section-header">
              <div>
                <div className="eyebrow">{t("user.generate.previewLabel")}</div>
                <h3 className="section-title">{t("user.generate.previewTitle")}</h3>
              </div>
              <Wand2 className="section-icon" />
            </div>

            <div className="generation-thumb generation-thumb-featured">
              <span>{t("user.viewer.previewPlaceholder")}</span>
            </div>

            <div className="detail-grid">
              <div className="detail-item">
                <div className="detail-label">{t("user.generate.latestResult")}</div>
                <div className="detail-value">{t(featuredTask.titleKey)}</div>
              </div>
              <div className="detail-item">
                <div className="detail-label">{t("user.generate.updatedAt")}</div>
                <div className="detail-value">{formatTimestamp(locale, featuredTask.updatedAt)}</div>
              </div>
            </div>

            <Link to={`/viewer/${featuredTask.id}`}>
              <Button variant="primary" className="full-width-button">
                {t("user.generate.openViewer")}
                <ArrowUpRight className="button-icon" />
              </Button>
            </Link>
          </Card>
        </div>
      </section>
    </div>
  );
}
