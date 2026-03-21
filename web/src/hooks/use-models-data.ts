import { useEffect, useState } from "react";

import type { ModelsData } from "@/data/admin-mocks";
import { fetchModels } from "@/lib/admin-api";

export function useModelsData() {
  const [data, setData] = useState<ModelsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchModels()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
