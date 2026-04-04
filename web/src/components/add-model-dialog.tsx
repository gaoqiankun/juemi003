import { useCallback, useEffect, useState } from "react";
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

const PROVIDER_OPTIONS = [
  { value: "trellis2", label: "TRELLIS2" },
  { value: "hunyuan3d", label: "HunYuan3D-2" },
  { value: "step1x3d", label: "Step1X-3D" },
];

const WEIGHT_SOURCE_OPTIONS: { value: WeightSource; labelKey: string }[] = [
  { value: "huggingface", labelKey: "models.addModel.sources.huggingface" },
  { value: "local", labelKey: "models.addModel.sources.local" },
  { value: "url", labelKey: "models.addModel.sources.url" },
];

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

  const [displayName, setDisplayName] = useState("");
  const [providerType, setProviderType] = useState("trellis2");
  const [weightSource, setWeightSource] = useState<WeightSource>("huggingface");
  const [hfPath, setHfPath] = useState("");
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

  useEffect(() => {
    if (!open || !providerType) return;

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
  }, [open, providerType]);

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

  const validate = useCallback((): string => {
    if (!displayName.trim()) return t("models.addModel.errors.displayNameRequired");
    if (!getAutoModelId()) return t("models.addModel.errors.idRequired");

    const path = getActivePath().trim();
    if (weightSource === "huggingface" && !HUGGINGFACE_REPO_PATTERN.test(path)) return t("models.addModel.errors.hfInvalid");
    if (weightSource === "local" && !path) return t("models.addModel.errors.localRequired");
    if (weightSource === "url" && !path.match(/^https?:\/\//)) return t("models.addModel.errors.urlInvalid");

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
  }, [displayName, getAutoModelId, getActivePath, weightSource, providerDeps, depChoices, newDepNames, newDepSources, newDepPaths, t]);

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
  }, [validate, getAutoModelId, providerDeps, depChoices, newDepSources, newDepPaths, newDepNames, displayName, providerType, getActivePath, weightSource, onSubmit, resetForm, onOpenChange]);

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
      <DialogContent className="flex max-h-[90vh] w-[min(92vw,560px)] flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle>{t("models.addModel.title")}</DialogTitle>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pt-1 pr-1">
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">{t("models.addModel.fields.displayName")}</label>
              <InputField value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="HunYuan3D-2" disabled={submitting} />
            </div>
            <div className="grid gap-1.5">
              <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">{t("models.addModel.fields.provider")}</label>
              <SelectField value={providerType} onValueChange={setProviderType} options={PROVIDER_OPTIONS} />
            </div>
          </div>

          <div className="grid gap-2">
            <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">{t("models.addModel.fields.weightSource")}</label>
            <div className="grid gap-2">
              {sourceRows.map(({ key, setPath, path }) => (
                <label
                  key={key}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border p-3 transition-colors",
                    !submitting && "cursor-pointer",
                    weightSource === key ? "border-accent-strong bg-surface-container-low" : "border-outline hover:bg-surface-container-lowest",
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
                  <span className="w-24 shrink-0 text-sm font-medium text-text-primary">{t(`models.addModel.sources.${key}`)}</span>
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

          {providerDepsLoading ? (
            <div className="grid gap-1.5 rounded-xl border border-outline bg-surface-container-low p-3">
              <p className="text-sm text-text-secondary">{t("models.addModel.deps.loading")}</p>
            </div>
          ) : null}

          {!providerDepsLoading && providerDeps.length > 0 ? (
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">{t("models.addModel.deps.sectionTitle")}</label>
              <div className="grid gap-2">
                {providerDeps.map((dep) => {
                  const depType = dep.dep_type;
                  const choice = depChoices[depType] || getDefaultDepChoice(dep);
                  const selectedInstanceId = getDepInstanceId(choice);
                  const selectedInstance = selectedInstanceId ? dep.instances.find((instance) => instance.id === selectedInstanceId) || null : null;
                  const isNew = !selectedInstanceId;
                  const depSource = newDepSources[depType] || "huggingface";
                  const depPath = newDepPaths[depType]?.[depSource] || "";
                  const depOptions = [
                    ...dep.instances.map((instance) => ({ value: `existing:${instance.id}`, label: `${instance.display_name} (${instance.download_status})` })),
                    { value: "new", label: t("models.addModel.deps.newInstance") },
                  ];

                  return (
                    <div key={depType} className="grid gap-2 rounded-xl border border-outline p-3">
                      <div className="grid gap-0.5">
                        <p className="text-sm font-semibold text-text-primary">{dep.description || dep.dep_type}</p>
                        <p className="break-all text-xs text-text-secondary">{dep.hf_repo_id}</p>
                      </div>

                      <SelectField value={choice} onValueChange={(nextChoice) => handleDepChoiceChange(dep, nextChoice)} options={depOptions} />

                      {selectedInstance ? (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-text-secondary">{selectedInstance.display_name}</span>
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
                            <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">{t("models.addModel.deps.nameLabel")}</label>
                            <InputField
                              value={newDepNames[depType] || ""}
                              onChange={(e) => setNewDepNames((prev) => ({ ...prev, [depType]: e.target.value }))}
                              placeholder={t("models.addModel.deps.namePlaceholder")}
                              disabled={submitting}
                            />
                          </div>

                          <div className="grid gap-1.5">
                            <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">{t("models.addModel.deps.sourceLabel")}</label>
                            <div className="grid gap-2">
                              <SelectField
                                value={depSource}
                                onValueChange={(value) => handleDepSourceChange(dep, value)}
                                options={WEIGHT_SOURCE_OPTIONS.map((source) => ({ value: source.value, label: t(source.labelKey) }))}
                              />
                              <InputField
                                value={depPath}
                                onChange={(e) => handleDepPathChange(dep, depSource, e.target.value)}
                                placeholder={t(`models.addModel.placeholders.${depSource}`)}
                                disabled={submitting}
                              />
                            </div>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

        </div>
        </div>

        {error ? <p className="shrink-0 pt-1 text-sm text-danger-text">{error}</p> : null}

        <div className="flex shrink-0 justify-end gap-2 pt-2">
          <Button type="button" variant="outline" size="sm" onClick={() => handleOpenChange(false)} disabled={submitting}>
            {t("models.addModel.cancel")}
          </Button>
          <Button type="button" variant="primary" size="sm" onClick={handleSubmit} disabled={submitting}>
            {submitting ? t("models.addModel.submitting") : t("models.addModel.submit")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
