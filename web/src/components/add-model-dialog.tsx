import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  InputField,
  SelectField,
} from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

type WeightSource = "huggingface" | "local" | "url";

const PROVIDER_OPTIONS = [
  { value: "trellis2", label: "TRELLIS2" },
  { value: "hunyuan3d", label: "HunYuan3D-2" },
  { value: "step1x3d", label: "Step1X-3D" },
];
const HUGGINGFACE_REPO_PATTERN = /^[^/\s]+\/[^/\s]+$/;

interface AddModelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: Record<string, unknown>) => Promise<void>;
}

export function AddModelDialog({ open, onOpenChange, onSubmit }: AddModelDialogProps) {
  const { t } = useTranslation();

  const [displayName, setDisplayName] = useState("");
  const [providerType, setProviderType] = useState("trellis2");
  const [weightSource, setWeightSource] = useState<WeightSource>("huggingface");
  const [hfPath, setHfPath] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [urlPath, setUrlPath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleDisplayNameChange = useCallback((value: string) => {
    setDisplayName(value);
  }, []);

  const getAutoModelId = useCallback(() => slugify(displayName), [displayName]);

  const getActivePath = useCallback((): string => {
    if (weightSource === "huggingface") return hfPath;
    if (weightSource === "local") return localPath;
    return urlPath;
  }, [weightSource, hfPath, localPath, urlPath]);

  const validate = useCallback((): string => {
    if (!displayName.trim()) return t("models.addModel.errors.displayNameRequired");
    if (!getAutoModelId()) return t("models.addModel.errors.idRequired");
    const path = getActivePath().trim();
    if (weightSource === "huggingface" && !HUGGINGFACE_REPO_PATTERN.test(path)) {
      return t("models.addModel.errors.hfInvalid");
    }
    if (weightSource === "local" && !path) {
      return t("models.addModel.errors.localRequired");
    }
    if (weightSource === "url" && !path.match(/^https?:\/\//)) {
      return t("models.addModel.errors.urlInvalid");
    }
    return "";
  }, [displayName, getAutoModelId, weightSource, getActivePath, t]);

  const resetForm = useCallback(() => {
    setDisplayName("");
    setProviderType("trellis2");
    setWeightSource("huggingface");
    setHfPath("");
    setLocalPath("");
    setUrlPath("");
    setError("");
  }, []);

  const handleSubmit = useCallback(async () => {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const modelId = getAutoModelId().trim();
      await onSubmit({
        id: modelId,
        displayName: displayName.trim(),
        providerType,
        modelPath: getActivePath().trim(),
        weightSource,
      });
      resetForm();
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    } finally {
      setSubmitting(false);
    }
  }, [validate, getAutoModelId, displayName, providerType, getActivePath, weightSource, onSubmit, resetForm, onOpenChange]);

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    if (!submitting) {
      if (!nextOpen) setError("");
      onOpenChange(nextOpen);
    }
  }, [submitting, onOpenChange]);

  const sourceRows: { key: WeightSource; setPath: (v: string) => void; path: string }[] = [
    { key: "huggingface", setPath: setHfPath, path: hfPath },
    { key: "local", setPath: setLocalPath, path: localPath },
    { key: "url", setPath: setUrlPath, path: urlPath },
  ];

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="w-[min(92vw,560px)]">
        <DialogHeader>
          <DialogTitle>{t("models.addModel.title")}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 pt-1">
          {/* Model Name + Model Type */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                {t("models.addModel.fields.displayName")}
              </label>
              <InputField
                value={displayName}
                onChange={(e) => handleDisplayNameChange(e.target.value)}
                placeholder="HunYuan3D-2"
                disabled={submitting}
              />
            </div>
            <div className="grid gap-1.5">
              <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                {t("models.addModel.fields.provider")}
              </label>
              <SelectField
                value={providerType}
                onValueChange={setProviderType}
                options={PROVIDER_OPTIONS}
              />
            </div>
          </div>

          {/* Weight Source */}
          <div className="grid gap-2">
            <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
              {t("models.addModel.fields.weightSource")}
            </label>
            <div className="grid gap-2">
              {sourceRows.map(({ key, setPath, path }) => (
                <label
                  key={key}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border p-3 transition-colors",
                    !submitting && "cursor-pointer",
                    weightSource === key
                      ? "border-accent-strong bg-surface-container-low"
                      : "border-outline hover:bg-surface-container-lowest",
                  )}
                >
                  <input
                    type="radio"
                    name="weightSource"
                    value={key}
                    checked={weightSource === key}
                    onChange={() => setWeightSource(key)}
                    className="accent-[var(--accent-strong)] shrink-0"
                    disabled={submitting}
                  />
                  <span className="w-24 shrink-0 text-sm font-medium text-text-primary">
                    {t(`models.addModel.sources.${key}`)}
                  </span>
                  <InputField
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    placeholder={t(`models.addModel.placeholders.${key}`)}
                    disabled={submitting || weightSource !== key}
                    className={cn("flex-1", weightSource !== key && "opacity-40")}
                  />
                </label>
              ))}
            </div>
          </div>

          {error ? <p className="text-sm text-danger-text">{error}</p> : null}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleOpenChange(false)}
              disabled={submitting}
            >
              {t("models.addModel.cancel")}
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting ? t("models.addModel.submitting") : t("models.addModel.submit")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
