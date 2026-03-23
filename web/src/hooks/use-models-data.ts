import { useCallback, useEffect, useState } from "react";

import {
  fetchModels,
  loadModel,
  updateModel,
  type RawAdminModelRecord,
} from "@/lib/admin-api";

export type AdminModelRuntimeState = "ready" | "loading" | "not_loaded" | "error" | "unknown";

export interface AdminModelItem {
  id: string;
  displayName: string;
  isEnabled: boolean;
  isDefault: boolean;
  runtimeState: AdminModelRuntimeState;
  tasksProcessed: number;
  maxTasksPerSlot: number;
  errorMessage: string;
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

function normalizeModels(payload: RawAdminModelRecord[] | undefined): AdminModelItem[] {
  if (!Array.isArray(payload)) {
    return [];
  }
  return payload
    .map((item) => {
      const id = String(item.id || "").trim();
      const displayName = String(item.display_name || item.id || "").trim();
      if (!id || !displayName) {
        return null;
      }
      return {
        id,
        displayName,
        isEnabled: Boolean(item.is_enabled),
        isDefault: Boolean(item.is_default),
        runtimeState: normalizeRuntimeState(String(item.runtime_state || item.runtimeState || "")),
        tasksProcessed: Number(item.tasks_processed || 0),
        maxTasksPerSlot: Number(item.max_tasks_per_slot || item.maxTasksPerSlot || 0),
        errorMessage: String(item.error_message || "").trim(),
      };
    })
    .filter((item): item is AdminModelItem => item !== null);
}

export function useModelsData() {
  const [models, setModels] = useState<AdminModelItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyModelId, setBusyModelId] = useState("");
  const pollingIntervalMs = models.some((model) => model.runtimeState === "loading") ? 3_000 : 10_000;

  const loadModels = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
    }
    try {
      const response = await fetchModels();
      setModels(normalizeModels(response.models));
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

  return {
    models,
    loading,
    error,
    busyModelId,
    refresh: loadModels,
    setModelEnabled,
    setModelDefault,
    requestModelLoad,
  };
}
