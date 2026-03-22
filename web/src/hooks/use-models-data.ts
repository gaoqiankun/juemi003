import { useCallback, useEffect, useState } from "react";

import {
  deleteModel,
  fetchModels,
  updateModel,
  type RawAdminModelRecord,
} from "@/lib/admin-api";

export interface AdminModelItem {
  id: string;
  displayName: string;
  isEnabled: boolean;
  isDefault: boolean;
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
      };
    })
    .filter((item): item is AdminModelItem => item !== null);
}

export function useModelsData() {
  const [models, setModels] = useState<AdminModelItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyModelId, setBusyModelId] = useState("");

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
  }, [loadModels]);

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

  const removeModel = useCallback(async (modelId: string) => {
    setBusyModelId(modelId);
    try {
      await deleteModel(modelId);
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
    removeModel,
  };
}
