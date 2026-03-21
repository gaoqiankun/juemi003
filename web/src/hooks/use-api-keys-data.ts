import { useEffect, useState } from "react";

import type { ApiKeysData, ApiUsageMetric } from "@/data/admin-mocks";
import { fetchAdminKeys, fetchKeysStats } from "@/lib/admin-api";

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
          keys: keysRes.keys,
        });
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
