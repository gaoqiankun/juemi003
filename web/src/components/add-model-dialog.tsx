import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, InputField, SelectField } from "@/components/ui/primitives";
import { fetchProviderDeps, type DepAssignment, type DepDownloadStatus, type ProviderDepType } from "@/lib/admin-api";
import { cn } from "@/lib/utils";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

type WeightSource = "huggingface" | "local" | "url";

interface ProviderMeta {
  label: string;
  vram: string;
  defaultModelPath: string;
  defaultDisplayName: string;
}

const PROVIDER_METADATA: Record<string, ProviderMeta> = {
  trellis2: {
    label: "TRELLIS2",
    vram: "24 GB",
    defaultModelPath: "microsoft/TRELLIS.2-4B",
    defaultDisplayName: "TRELLIS2",
  },
  hunyuan3d: {
    label: "HunYuan3D-2",
    vram: "24 GB",
    defaultModelPath: "tencent/Hunyuan3D-2",
    defaultDisplayName: "HunYuan3D-2",
  },
  step1x3d: {
    label: "Step1X-3D",
    vram: "16 GB",
    defaultModelPath: "stepfun-ai/Step1X-3D",
    defaultDisplayName: "Step1X-3D",
  },
};

const PROVIDER_KEYS = Object.keys(PROVIDER_METADATA);

interface WeightSourcePickerProps {
  source: WeightSource;
  path: string;
  onSourceChange: (source: WeightSource) => void;
  onPathChange: (value: string) => void;
  disabled?: boolean;
  radioName: string;
  label?: string;
}

function WeightSourcePicker({ source, path, onSourceChange, onPathChange, disabled, radioName, label }: WeightSourcePickerProps) {
  const { t } = useTranslation();
  return (
    <div className="grid gap-2">
      <div className="flex items-center gap-4">
        {label && <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-text-secondary">{label}</span>}
        {(["huggingface", "local", "url"] as WeightSource[]).map((key) => (
          <label
            key={key}
            className={cn(
              "flex items-center gap-1.5 text-sm",
              disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
            )}
          >
            <input
              type="radio"
              name={radioName}
              value={key}
              checked={source === key}
              onChange={() => onSourceChange(key)}
              disabled={disabled}
              className="accent-[var(--accent-strong)]"
            />
            {t(`models.addModel.sources.${key}`)}
          </label>
        ))}
      </div>
      <InputField
        value={path}
        onChange={(e) => onPathChange(e.target.value)}
        placeholder={t(`models.addModel.placeholders.${source}`)}
        disabled={disabled}
      />
    </div>
  );
}

const DEP_STATUS_CLASS: Record<DepDownloadStatus, string> = {
  done: "text-success-text",
  downloading: "text-accent-strong",
  error: "text-danger-text",
  pending: "text-text-secondary",
};

const HUGGINGFACE_REPO_PATTERN = /^[^/\s]+\/[^/\s]+$/;

interface AddModelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: Record<string, unknown>) => Promise<void>;
}

function normalizeWeightSource(value: string): WeightSource {
  if (value === "local" || value === "url") return value;
  return "huggingface";
}

function getDefaultDepChoice(dep: ProviderDepType): string {
  return dep.instances.length > 0 ? `existing:${dep.instances[0].id}` : "new";
}

function getDepInstanceId(choice: string): string {
  return choice.startsWith("existing:") ? choice.slice("existing:".length).trim() : "";
}

function createDepSourcePaths(hfRepoId: string): Record<WeightSource, string> {
  return { huggingface: String(hfRepoId || "").trim(), local: "", url: "" };
}

export function AddModelDialog({ open, onOpenChange, onSubmit }: AddModelDialogProps) {
  const { t } = useTranslation();

  const [step, setStep] = useState(1);
  const [providerType, setProviderType] = useState("trellis2");
  const [displayName, setDisplayName] = useState(PROVIDER_METADATA.trellis2.defaultDisplayName);
  const [weightSource, setWeightSource] = useState<WeightSource>("huggingface");
  const [hfPath, setHfPath] = useState(PROVIDER_METADATA.trellis2.defaultModelPath);
  const [localPath, setLocalPath] = useState("");
  const [urlPath, setUrlPath] = useState("");

  const [providerDeps, setProviderDeps] = useState<ProviderDepType[]>([]);
  const [providerDepsLoading, setProviderDepsLoading] = useState(false);
  const [depChoices, setDepChoices] = useState<Record<string, string>>({});
  const [newDepNames, setNewDepNames] = useState<Record<string, string>>({});
  const [newDepSources, setNewDepSources] = useState<Record<string, WeightSource>>({});
  const [newDepPaths, setNewDepPaths] = useState<Record<string, Record<WeightSource, string>>>({});

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Track which provider's deps have already been fetched so navigating back preserves choices
  const fetchedForProviderRef = useRef<string | null>(null);

  // Prefill step 2 state when provider changes
  useEffect(() => {
    const meta = PROVIDER_METADATA[providerType];
    if (!meta) return;
    setDisplayName(meta.defaultDisplayName);
    setHfPath(meta.defaultModelPath);
    setWeightSource("huggingface");
    setLocalPath("");
    setUrlPath("");
  }, [providerType]);

  // Fetch deps when entering step 3
  useEffect(() => {
    if (step !== 3 || !open) return;
    if (fetchedForProviderRef.current === providerType) return;

    fetchedForProviderRef.current = providerType;
    let cancelled = false;
    setProviderDeps([]);
    setDepChoices({});
    setNewDepNames({});
    setNewDepSources({});
    setNewDepPaths({});
    setProviderDepsLoading(true);

    fetchProviderDeps(providerType)
      .then((deps) => {
        if (cancelled) return;
        setProviderDeps(deps);

        const choices: Record<string, string> = {};
        const names: Record<string, string> = {};
        const sources: Record<string, WeightSource> = {};
        const paths: Record<string, Record<WeightSource, string>> = {};

        for (const dep of deps) {
          paths[dep.dep_type] = createDepSourcePaths(dep.hf_repo_id);
          if (dep.instances.length > 0) {
            choices[dep.dep_type] = `existing:${dep.instances[0].id}`;
            continue;
          }
          choices[dep.dep_type] = "new";
          names[dep.dep_type] = dep.dep_type;
          sources[dep.dep_type] = "huggingface";
        }

        setDepChoices(choices);
        setNewDepNames(names);
        setNewDepSources(sources);
        setNewDepPaths(paths);

        if (!cancelled && deps.length === 0) {
          setStep(4);
        }
      })
      .catch(() => {
        if (!cancelled) setProviderDeps([]);
      })
      .finally(() => {
        if (!cancelled) setProviderDepsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [step, open, providerType]);

  const ensureNewDepDraft = useCallback((dep: ProviderDepType) => {
    setNewDepNames((prev) => (prev[dep.dep_type] ? prev : { ...prev, [dep.dep_type]: dep.dep_type }));
    setNewDepSources((prev) => (prev[dep.dep_type] ? prev : { ...prev, [dep.dep_type]: "huggingface" }));
    setNewDepPaths((prev) => (prev[dep.dep_type] ? prev : { ...prev, [dep.dep_type]: createDepSourcePaths(dep.hf_repo_id) }));
  }, []);

  const handleDepChoiceChange = useCallback((dep: ProviderDepType, choice: string) => {
    setDepChoices((prev) => ({ ...prev, [dep.dep_type]: choice }));
    if (choice === "new") ensureNewDepDraft(dep);
  }, [ensureNewDepDraft]);

  const handleDepSourceChange = useCallback((dep: ProviderDepType, sourceValue: string) => {
    ensureNewDepDraft(dep);
    const source = normalizeWeightSource(sourceValue);
    setNewDepSources((prev) => ({ ...prev, [dep.dep_type]: source }));
  }, [ensureNewDepDraft]);

  const handleDepPathChange = useCallback((dep: ProviderDepType, source: WeightSource, value: string) => {
    setNewDepPaths((prev) => {
      const current = prev[dep.dep_type] || createDepSourcePaths(dep.hf_repo_id);
      return { ...prev, [dep.dep_type]: { ...current, [source]: value } };
    });
  }, []);

  const getAutoModelId = useCallback(() => slugify(displayName), [displayName]);

  const getActivePath = useCallback((): string => {
    if (weightSource === "huggingface") return hfPath;
    if (weightSource === "local") return localPath;
    return urlPath;
  }, [weightSource, hfPath, localPath, urlPath]);

  const activeMainPath = weightSource === "huggingface" ? hfPath : weightSource === "local" ? localPath : urlPath;
  const setActiveMainPath = useCallback((value: string) => {
    if (weightSource === "huggingface") setHfPath(value);
    else if (weightSource === "local") setLocalPath(value);
    else setUrlPath(value);
  }, [weightSource]);

  const validateStep2 = useCallback((): string => {
    if (!displayName.trim()) return t("models.addModel.errors.displayNameRequired");
    if (!getAutoModelId()) return t("models.addModel.errors.idRequired");
    const path = getActivePath().trim();
    if (weightSource === "huggingface" && !HUGGINGFACE_REPO_PATTERN.test(path)) return t("models.addModel.errors.hfInvalid");
    if (weightSource === "local" && !path) return t("models.addModel.errors.localRequired");
    if (weightSource === "url" && !path.match(/^https?:\/\//)) return t("models.addModel.errors.urlInvalid");
    return "";
  }, [displayName, getAutoModelId, getActivePath, weightSource, t]);

  const validateStep3 = useCallback((): string => {
    for (const dep of providerDeps) {
      const depType = dep.dep_type;
      const choice = depChoices[depType] || getDefaultDepChoice(dep);
      if (choice.startsWith("existing:") && getDepInstanceId(choice)) continue;

      const name = String(newDepNames[depType] || "").trim();
      if (!name) return t("models.addModel.errors.depNameRequired", { depType });

      const source = newDepSources[depType] || "huggingface";
      const depPath = String(newDepPaths[depType]?.[source] || "").trim();
      if (source === "huggingface" && !HUGGINGFACE_REPO_PATTERN.test(depPath)) return t("models.addModel.errors.depHfInvalid", { depType });
      if (source === "local" && !depPath) return t("models.addModel.errors.depLocalRequired", { depType });
      if (source === "url" && !depPath.match(/^https?:\/\//)) return t("models.addModel.errors.depUrlInvalid", { depType });

      const duplicate = dep.instances.find((inst) => {
        if (inst.weight_source !== source) return false;
        const instPath = String(inst.dep_model_path || "").trim() || String(inst.hf_repo_id || "").trim();
        const newPath = source === "huggingface" ? (String(newDepPaths[depType]?.huggingface || "").trim() || dep.hf_repo_id) : depPath;
        return instPath === newPath;
      });
      if (duplicate) return t("models.addModel.errors.depDuplicate", { depType, name: duplicate.display_name });
    }
    return "";
  }, [providerDeps, depChoices, newDepNames, newDepSources, newDepPaths, t]);

  const handleNext = useCallback(() => {
    setError("");
    if (step === 2) {
      const err = validateStep2();
      if (err) { setError(err); return; }
    } else if (step === 3) {
      const err = validateStep3();
      if (err) { setError(err); return; }
    }
    setStep((s) => Math.min(s + 1, 4));
  }, [step, validateStep2, validateStep3]);

  const handleBack = useCallback(() => {
    setError("");
    if (step === 4 && providerDeps.length === 0) {
      setStep(2);
    } else {
      setStep((s) => Math.max(s - 1, 1));
    }
  }, [step, providerDeps.length]);

  const resetForm = useCallback(() => {
    setStep(1);
    setProviderType("trellis2");
    setDisplayName(PROVIDER_METADATA.trellis2.defaultDisplayName);
    setWeightSource("huggingface");
    setHfPath(PROVIDER_METADATA.trellis2.defaultModelPath);
    setLocalPath("");
    setUrlPath("");
    setProviderDeps([]);
    setDepChoices({});
    setNewDepNames({});
    setNewDepSources({});
    setNewDepPaths({});
    setProviderDepsLoading(false);
    setError("");
    fetchedForProviderRef.current = null;
  }, []);

  const handleSubmit = useCallback(async () => {
    setSubmitting(true);
    setError("");

    try {
      const modelId = getAutoModelId().trim();
      const depAssignments: Record<string, DepAssignment> = {};
      const fallbackTimestamp = Date.now();

      for (const dep of providerDeps) {
        const depType = dep.dep_type;
        const choice = depChoices[depType] || getDefaultDepChoice(dep);
        const existingId = getDepInstanceId(choice);
        if (existingId) {
          depAssignments[depType] = { instance_id: existingId };
          continue;
        }

        const source = newDepSources[depType] || "huggingface";
        const depPath = String(newDepPaths[depType]?.[source] || "").trim();
        const name = String(newDepNames[depType] || depType).trim();
        const instanceId = slugify(name) || `${depType}-${fallbackTimestamp}`;
        depAssignments[depType] = { new: { instance_id: instanceId, display_name: name, weight_source: source, dep_model_path: depPath } };
      }

      await onSubmit({
        id: modelId,
        displayName: displayName.trim(),
        providerType,
        modelPath: getActivePath().trim(),
        weightSource,
        depAssignments,
      });
      resetForm();
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    } finally {
      setSubmitting(false);
    }
  }, [getAutoModelId, providerDeps, depChoices, newDepSources, newDepPaths, newDepNames, displayName, providerType, getActivePath, weightSource, onSubmit, resetForm, onOpenChange]);

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    if (!submitting) {
      if (!nextOpen) resetForm();
      onOpenChange(nextOpen);
    }
  }, [submitting, resetForm, onOpenChange]);

  const allDepsReused = providerDeps.length > 0 && providerDeps.every((dep) => {
    const choice = depChoices[dep.dep_type] || getDefaultDepChoice(dep);
    return choice.startsWith("existing:");
  });

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-[min(92vw,640px)] flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle>{t("models.addModel.title")}</DialogTitle>
          <div className="flex items-center pt-3">
            {[1, 2, 3, 4].map((s, idx) => (
              <div key={s} className="flex items-center">
                {idx > 0 && (
                  <div className={cn("h-px w-8 transition-colors", step >= s ? "bg-accent-strong" : "bg-outline")} />
                )}
                <div
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                    step === s
                      ? "bg-accent-strong text-white"
                      : step > s
                      ? "bg-accent-strong/20 text-accent-strong"
                      : "border border-outline bg-surface-container-low text-text-secondary",
                  )}
                >
                  {s}
                </div>
              </div>
            ))}
          </div>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pt-1 pr-1">

          {/* Step 1: Choose provider */}
          {step === 1 && (
            <div className="grid gap-3">
              {PROVIDER_KEYS.map((key) => {
                const meta = PROVIDER_METADATA[key];
                const isSelected = providerType === key;
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setProviderType(key)}
                    className={cn(
                      "grid gap-1 rounded-xl border p-4 text-left transition-colors select-none",
                      isSelected
                        ? "border-accent-strong bg-accent-strong/5"
                        : "border-outline bg-surface-container-low",
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-semibold text-text-primary">{meta.label}</span>
                      <span className="shrink-0 text-xs text-text-secondary">
                        {t("models.addModel.providerCard.vram", { vram: meta.vram })}
                      </span>
                    </div>
                    <p className="text-xs text-text-secondary">{t(`models.addModel.providerCard.desc.${key}`)}</p>
                  </button>
                );
              })}
            </div>
          )}

          {/* Step 2: Configure main model weights */}
          {step === 2 && (
            <div className="grid gap-4">
              <div className="grid gap-1.5">
                <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                  {t("models.addModel.fields.displayName")}
                </label>
                <InputField
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="HunYuan3D-2"
                  disabled={submitting}
                />
              </div>
              <WeightSourcePicker
                source={weightSource}
                path={activeMainPath}
                onSourceChange={setWeightSource}
                onPathChange={setActiveMainPath}
                disabled={submitting}
                radioName="weightSource"
                label={t("models.addModel.fields.weightSource")}
              />
              <p className="text-xs text-text-secondary">{t("models.addModel.step2.autoDownloadNote")}</p>
            </div>
          )}

          {/* Step 3: Configure deps */}
          {step === 3 && (
            <div className="grid gap-3">
              {providerDepsLoading ? (
                <div className="rounded-xl border border-outline bg-surface-container-low p-3">
                  <p className="text-sm text-text-secondary">{t("models.addModel.deps.loading")}</p>
                </div>
              ) : (
                <>
                  <p className="text-xs text-text-secondary">{t("models.addModel.step3.autoDownloadNote")}</p>
                  {providerDeps.map((dep) => {
                    const depType = dep.dep_type;
                    const choice = depChoices[depType] || getDefaultDepChoice(dep);
                    const selectedInstanceId = getDepInstanceId(choice);
                    const selectedInstance = selectedInstanceId
                      ? dep.instances.find((inst) => inst.id === selectedInstanceId) || null
                      : null;
                    const isNew = !selectedInstanceId;
                    const depSource = newDepSources[depType] || "huggingface";
                    const depPath = newDepPaths[depType]?.[depSource] || "";
                    const depOptions = [
                      ...dep.instances.map((inst) => ({
                        value: `existing:${inst.id}`,
                        label: `${inst.display_name} (${inst.download_status})`,
                      })),
                      { value: "new", label: t("models.addModel.deps.newInstance") },
                    ];

                    return (
                      <div key={depType} className="grid gap-2 rounded-xl border border-outline p-3">
                        <div className="grid gap-0.5">
                          <p className="text-sm font-semibold text-text-primary">{dep.description || dep.dep_type}</p>
                          <p className="break-all text-xs text-text-secondary">{dep.hf_repo_id}</p>
                        </div>
                        <SelectField
                          value={choice}
                          onValueChange={(nextChoice) => handleDepChoiceChange(dep, nextChoice)}
                          options={depOptions}
                        />
                        {selectedInstance ? (
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-text-secondary">{t("models.addModel.step3.reusingExisting")}</span>
                            <span
                              className={cn(
                                "inline-flex items-center rounded-full border border-outline bg-surface-container-low px-2 py-0.5 text-[11px] font-medium",
                                DEP_STATUS_CLASS[selectedInstance.download_status],
                              )}
                            >
                              {selectedInstance.download_status}
                            </span>
                          </div>
                        ) : null}
                        {isNew ? (
                          <div className="grid gap-2 rounded-lg border border-outline bg-surface-container-low p-3">
                            <div className="grid gap-1.5">
                              <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                                {t("models.addModel.deps.nameLabel")}
                              </label>
                              <InputField
                                value={newDepNames[depType] || ""}
                                onChange={(e) => setNewDepNames((prev) => ({ ...prev, [depType]: e.target.value }))}
                                placeholder={t("models.addModel.deps.namePlaceholder")}
                                disabled={submitting}
                              />
                            </div>
                            <WeightSourcePicker
                              source={depSource}
                              path={depPath}
                              onSourceChange={(value) => handleDepSourceChange(dep, value)}
                              onPathChange={(value) => handleDepPathChange(dep, depSource, value)}
                              disabled={submitting}
                              radioName={`depSource-${depType}`}
                              label={t("models.addModel.deps.sourceLabel")}
                            />
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                  {allDepsReused && (
                    <p className="text-xs text-text-secondary">{t("models.addModel.step3.noDownloadNeeded")}</p>
                  )}
                </>
              )}
            </div>
          )}

          {/* Step 4: Confirm */}
          {step === 4 && (
            <div className="grid gap-3">
              <p className="text-sm font-semibold text-text-primary">{t("models.addModel.step4.title")}</p>
              <div className="grid gap-2">
                <div className="rounded-xl border border-outline bg-surface-container-low p-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                    {t("models.addModel.step4.mainModel")}
                  </p>
                  <p className="mt-1 text-sm font-medium text-text-primary">{displayName}</p>
                  <p className="text-xs text-text-secondary">
                    {PROVIDER_METADATA[providerType]?.label} · {getActivePath()}
                  </p>
                </div>
                {providerDeps.map((dep) => {
                  const depType = dep.dep_type;
                  const choice = depChoices[depType] || getDefaultDepChoice(dep);
                  const selectedInstanceId = getDepInstanceId(choice);
                  const selectedInstance = selectedInstanceId
                    ? dep.instances.find((inst) => inst.id === selectedInstanceId) || null
                    : null;
                  const depSource = newDepSources[depType] || "huggingface";
                  const depPath = newDepPaths[depType]?.[depSource] || dep.hf_repo_id;

                  return (
                    <div key={depType} className="rounded-xl border border-outline bg-surface-container-low p-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                        {t("models.addModel.step4.dep")}
                      </p>
                      <p className="mt-1 text-sm font-medium text-text-primary">{dep.description || dep.dep_type}</p>
                      {selectedInstance ? (
                        <p className="text-xs text-text-secondary">
                          {t("models.addModel.step4.reusingExisting", { name: selectedInstance.display_name })}
                        </p>
                      ) : (
                        <p className="text-xs text-text-secondary">
                          {depSource === "huggingface" ? "HuggingFace" : depSource} · {depPath}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

        </div>

        {error ? <p className="shrink-0 pt-1 text-sm text-danger-text">{error}</p> : null}

        <div className="flex shrink-0 items-center justify-between gap-2 pt-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={step === 1 ? () => handleOpenChange(false) : handleBack}
            disabled={submitting}
          >
            {step === 1 ? t("models.addModel.cancel") : t("models.addModel.back")}
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={step === 4 ? handleSubmit : handleNext}
            disabled={submitting || (step === 3 && providerDepsLoading)}
          >
            {step === 4
              ? submitting
                ? t("models.addModel.submitting")
                : t("models.addModel.startDownload")
              : t("models.addModel.next")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
