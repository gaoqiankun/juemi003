import { useEffect, useState } from "react";

import type { SettingsData } from "@/data/admin-mocks";
import { fetchSettings } from "@/lib/admin-api";

export function useSettingsData() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
