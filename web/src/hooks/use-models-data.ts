import { useCallback, useEffect, useState } from "react";

import {
  createModel,
  deleteModel,
  fetchModels,
  loadModel,
  updateModel,
  type RawAdminModelRecord,
} from "@/lib/admin-api";

export type AdminModelRuntimeState = "ready" | "loading" | "not_loaded" | "error" | "unknown";
export type AdminModelWeightSource = "huggingface" | "url" | "local";
export type AdminModelProviderType = "trellis2" | "hunyuan3d" | "step1x3d";

export interface AdminModelItem {
  id: string;
  displayName: string;
  modelPath: string;
  weightSource: AdminModelWeightSource;
  isEnabled: boolean;
  isDefault: boolean;
  runtimeState: AdminModelRuntimeState;
  tasksProcessed: number;
  maxTasksPerSlot: number;
  errorMessage: string;
}

export interface AdminPendingItem {
  id: string;
  displayName: string;
  modelPath: string;
  weightSource: AdminModelWeightSource;
  providerType: AdminModelProviderType;
  downloadStatus: "downloading" | "error";
  downloadProgress: number;
  downloadSpeedBps: number;
  downloadError: string;
}

function normalizeRuntimeState(runtimeState: string): AdminModelRuntimeState {
  const normalized = String(runtimeState || "").trim().toLowerCase();
  if (
    normalized === "ready"
    || normalized === "loading"
    || normalized === "not_loaded"
    || normalized === "error"
    || normalized === "unknown"
  ) {
    return normalized;
  }
  return "unknown";
}

function normalizeWeightSource(raw: string | undefined): AdminModelWeightSource {
  if (raw === "url" || raw === "local") return raw;
  return "huggingface";
}

function normalizeProviderType(raw: string | undefined): AdminModelProviderType {
  if (raw === "hunyuan3d" || raw === "step1x3d") return raw;
  return "trellis2";
}

function splitModels(payload: RawAdminModelRecord[] | undefined): {
  models: AdminModelItem[];
  pendingItems: AdminPendingItem[];
} {
  if (!Array.isArray(payload)) return { models: [], pendingItems: [] };

  const models: AdminModelItem[] = [];
  const pendingItems: AdminPendingItem[] = [];

  for (const item of payload) {
    const downloadStatus = String(item.download_status || "done").trim().toLowerCase();
    const id = String(item.id || "").trim();
    const displayName = String(item.display_name || item.id || "").trim();
    if (!id || !displayName) continue;

    if (downloadStatus === "downloading" || downloadStatus === "error") {
      pendingItems.push({
        id,
        displayName,
        modelPath: String(item.model_path || "").trim(),
        weightSource: normalizeWeightSource(item.weight_source),
        providerType: normalizeProviderType(String(item.provider_type || item.providerType || "").trim()),
        downloadStatus,
        downloadProgress: Number(item.download_progress ?? 0),
        downloadSpeedBps: Number(item.download_speed_bps ?? 0),
        downloadError: String(item.download_error || "").trim(),
      });
    } else {
      models.push({
        id,
        displayName,
        modelPath: String(item.model_path || "").trim(),
        weightSource: normalizeWeightSource(item.weight_source),
        isEnabled: Boolean(item.is_enabled),
        isDefault: Boolean(item.is_default),
        runtimeState: normalizeRuntimeState(String(item.runtime_state || item.runtimeState || "")),
        tasksProcessed: Number(item.tasks_processed || 0),
        maxTasksPerSlot: Number(item.max_tasks_per_slot || item.maxTasksPerSlot || 0),
        errorMessage: String(item.error_message || "").trim(),
      });
    }
  }

  return { models, pendingItems };
}

export function useModelsData() {
  const [models, setModels] = useState<AdminModelItem[]>([]);
  const [pendingItems, setPendingItems] = useState<AdminPendingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyModelId, setBusyModelId] = useState("");

  const hasDownloading = pendingItems.some((p) => p.downloadStatus === "downloading");
  const hasLoadingRuntime = models.some((m) => m.runtimeState === "loading");
  const pollingIntervalMs = hasDownloading ? 2_000 : hasLoadingRuntime ? 3_000 : 10_000;

  const loadModels = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
    }
    try {
      const response = await fetchModels(true);
      const { models: nextModels, pendingItems: nextPending } = splitModels(response.models);
      setModels(nextModels);
      setPendingItems(nextPending);
      setError(null);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : String(fetchError));
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    loadModels().catch(() => undefined);
    const timer = window.setInterval(() => {
      loadModels(true).catch(() => undefined);
    }, pollingIntervalMs);
    return () => {
      window.clearInterval(timer);
    };
  }, [loadModels, pollingIntervalMs]);

  const setModelEnabled = useCallback(async (modelId: string, enabled: boolean) => {
    setBusyModelId(modelId);
    try {
      await updateModel(modelId, { isEnabled: enabled });
      await loadModels(true);
    } finally {
      setBusyModelId("");
    }
  }, [loadModels]);

  const setModelDefault = useCallback(async (modelId: string) => {
    setBusyModelId(modelId);
    try {
      await updateModel(modelId, { isDefault: true });
      await loadModels(true);
    } finally {
      setBusyModelId("");
    }
  }, [loadModels]);

  const requestModelLoad = useCallback(async (modelId: string) => {
    setBusyModelId(modelId);
    try {
      await loadModel(modelId);
      await loadModels(true);
    } finally {
      setBusyModelId("");
    }
  }, [loadModels]);

  const addModel = useCallback(async (data: Record<string, unknown>) => {
    await createModel(data);
    await loadModels(true);
  }, [loadModels]);

  const cancelDownload = useCallback(async (modelId: string) => {
    await deleteModel(modelId);
    await loadModels(true);
  }, [loadModels]);

  const removeModel = useCallback(async (modelId: string) => {
    await deleteModel(modelId);
    await loadModels(true);
  }, [loadModels]);

  const retryDownload = useCallback(async (
    modelId: string,
    data: Record<string, unknown>,
  ) => {
    await deleteModel(modelId);
    await createModel(data);
    await loadModels(true);
  }, [loadModels]);

  return {
    models,
    pendingItems,
    loading,
    error,
    busyModelId,
    refresh: loadModels,
    setModelEnabled,
    setModelDefault,
    requestModelLoad,
    addModel,
    cancelDownload,
    removeModel,
    retryDownload,
  };
}
