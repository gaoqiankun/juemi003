import { useEffect, useState } from "react";

import type { DashboardData } from "@/data/admin-mocks";
import { fetchDashboard } from "@/lib/admin-api";

type RecentTaskWithOwnerHints = DashboardData["recentTasks"][number] & {
  keyId?: string;
  key_id?: string;
  keyLabel?: string;
  key_label?: string;
};

function normalizeOwner(task: RecentTaskWithOwnerHints) {
  const label = String(task.keyLabel || task.key_label || "").trim();
  if (label) {
    return label;
  }
  const owner = String(task.owner || "").trim();
  if (owner && owner !== "-") {
    return owner;
  }
  const keyId = String(task.keyId || task.key_id || "").trim();
  if (!keyId) {
    return "-";
  }
  return `${keyId.slice(0, 8)}${keyId.length > 8 ? "…" : ""}`;
}

export function useDashboardData() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDashboard()
      .then((payload) => {
        const recentTasks = Array.isArray(payload.recentTasks)
          ? payload.recentTasks.map((task) => ({
            ...task,
            owner: normalizeOwner(task as RecentTaskWithOwnerHints),
          }))
          : [];
        setData({
          ...payload,
          recentTasks,
        });
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
