import { useEffect, useState } from "react";

import type { ApiKeyData, ApiKeysData, ApiUsageMetric } from "@/data/admin-mocks";
import { fetchAdminKeys, fetchKeysStats, type RawAdminKeyItem } from "@/lib/admin-api";

function normalizeKeysResponse(payload: RawAdminKeyItem[] | { keys?: RawAdminKeyItem[] }): RawAdminKeyItem[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (payload && Array.isArray(payload.keys)) {
    return payload.keys;
  }
  return [];
}

function toApiKeyData(item: RawAdminKeyItem): ApiKeyData {
  const keyId = String(item.keyId || item.key_id || "");
  const createdAt = String(item.createdAt || item.created_at || new Date().toISOString());
  return {
    id: keyId,
    name: String(item.label || keyId || "API Key"),
    prefix: keyId.slice(0, 8) || "key_",
    createdAt,
    lastUsedAt: String(item.lastUsedAt || item.last_used_at || createdAt),
    requests: Number(item.requests || 0),
    scopes: Array.isArray(item.scopes) ? item.scopes : [],
    status: Boolean(item.isActive ?? item.is_active ?? true) ? "active" : "paused",
    owner: String(item.owner || "-"),
  };
}

export function useApiKeysData() {
  const [data, setData] = useState<ApiKeysData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchAdminKeys(), fetchKeysStats()])
      .then(([keysRes, statsRes]) => {
        const usage: ApiUsageMetric[] = [
          { key: "requests", value: statsRes.total_requests },
          { key: "projects", value: statsRes.active_keys },
          { key: "spend", value: 0 },
          { key: "errorRate", value: 0 },
        ];
        setData({
          usage,
          keys: normalizeKeysResponse(keysRes).map(toApiKeyData),
        });
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
