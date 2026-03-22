import { useEffect, useState } from "react";

import type { ModelsData } from "@/data/admin-mocks";
import { fetchModels } from "@/lib/admin-api";

interface RawModelRecord {
  id?: string;
  provider_type?: string;
  display_name?: string;
  model_path?: string;
  is_enabled?: boolean;
  is_default?: boolean;
  min_vram_mb?: number;
  runtimeState?: string;
  updated_at?: string | null;
  created_at?: string | null;
}

interface RawModelsResponse {
  models?: RawModelRecord[];
}

function mapRuntimeStateToStatus(runtimeState: string, isEnabled: boolean) {
  if (!isEnabled) {
    return "queued" as const;
  }
  if (runtimeState === "ready") {
    return "ready" as const;
  }
  if (runtimeState === "loading") {
    return "syncing" as const;
  }
  return "queued" as const;
}

function inferCapabilities(providerType: string) {
  if (providerType === "hunyuan3d") {
    return ["highDetail", "textureAware", "cleanTopology"];
  }
  if (providerType === "step1x3d") {
    return ["fastDraft", "multiView", "cleanTopology"];
  }
  return ["highDetail", "pbr", "multiView"];
}

function extractVersion(modelPath: string) {
  const parts = modelPath.split("/").filter(Boolean);
  return parts[parts.length - 1] || modelPath || "N/A";
}

function mapModelsData(response: RawModelsResponse): ModelsData {
  const nowIso = new Date().toISOString();
  const models = (response.models || []).map((model) => {
    const providerType = String(model.provider_type || "unknown").trim().toLowerCase();
    const displayName = String(model.display_name || model.id || "Unknown model").trim();
    const runtimeState = String(model.runtimeState || "").trim().toLowerCase();
    const isEnabled = Boolean(model.is_enabled);
    const status = mapRuntimeStateToStatus(runtimeState, isEnabled);
    const minVramGb = Math.max(1, Math.round((Number(model.min_vram_mb || 0) || 0) / 1024));
    const estimatedFootprintGb = Math.max(1, Math.round(minVramGb * 0.6 * 10) / 10);
    const progress = status === "ready" ? 100 : status === "syncing" ? 50 : 0;
    return {
      id: String(model.id || ""),
      name: displayName,
      provider: providerType || "unknown",
      version: extractVersion(String(model.model_path || "")),
      status,
      sizeGb: estimatedFootprintGb,
      minVramGb,
      downloads: 0,
      progress,
      capabilities: inferCapabilities(providerType),
      updatedAt: String(model.updated_at || model.created_at || nowIso),
    };
  });

  const ready = models.filter((model) => model.status === "ready").length;
  const syncing = models.filter((model) => model.status === "syncing").length;
  const queued = models.filter((model) => model.status === "queued").length;
  const storageUsedGb = models.reduce((acc, model) => acc + model.sizeGb, 0);

  return {
    models,
    summary: {
      ready,
      syncing,
      queued,
      storageUsedGb,
    },
  };
}

export function useModelsData() {
  const [data, setData] = useState<ModelsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchModels()
      .then((response) => setData(mapModelsData(response)))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
