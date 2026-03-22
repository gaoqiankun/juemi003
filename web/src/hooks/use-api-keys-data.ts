import { useCallback, useEffect, useState } from "react";

import {
  createAdminKey,
  deleteAdminKey,
  fetchAdminKeys,
  setAdminKeyActive,
  type RawAdminKeyItem,
} from "@/lib/admin-api";

export interface AdminApiKeyItem {
  id: string;
  label: string;
  createdAt: string;
  isActive: boolean;
}

export interface CreatedApiKey {
  keyId: string;
  token: string;
  label: string;
  createdAt: string;
}

function normalizeKeysResponse(payload: RawAdminKeyItem[] | { keys?: RawAdminKeyItem[] }): RawAdminKeyItem[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (payload && Array.isArray(payload.keys)) {
    return payload.keys;
  }
  return [];
}

function toApiKeyData(item: RawAdminKeyItem): AdminApiKeyItem | null {
  const keyId = String(item.keyId || item.key_id || "").trim();
  if (!keyId) {
    return null;
  }
  const createdAt = String(item.createdAt || item.created_at || new Date().toISOString()).trim();
  return {
    id: keyId,
    label: String(item.label || keyId || "API Key"),
    createdAt,
    isActive: Boolean(item.isActive ?? item.is_active ?? true),
  };
}

export function useApiKeysData() {
  const [keys, setKeys] = useState<AdminApiKeyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [busyKeyId, setBusyKeyId] = useState("");

  const refresh = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
    }
    try {
      const keysRes = await fetchAdminKeys();
      setKeys(
        normalizeKeysResponse(keysRes)
          .map(toApiKeyData)
          .filter((item): item is AdminApiKeyItem => item !== null),
      );
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
    refresh().catch(() => undefined);
  }, [refresh]);

  const createKey = useCallback(async (label: string): Promise<CreatedApiKey> => {
    setIsCreating(true);
    try {
      const created = await createAdminKey(label);
      await refresh(true);
      return {
        keyId: created.keyId,
        token: created.token,
        label: created.label,
        createdAt: created.createdAt,
      };
    } finally {
      setIsCreating(false);
    }
  }, [refresh]);

  const setKeyActive = useCallback(async (keyId: string, isActive: boolean) => {
    setBusyKeyId(keyId);
    try {
      await setAdminKeyActive(keyId, isActive);
      await refresh(true);
    } finally {
      setBusyKeyId("");
    }
  }, [refresh]);

  const removeKey = useCallback(async (keyId: string) => {
    setBusyKeyId(keyId);
    try {
      await deleteAdminKey(keyId);
      await refresh(true);
    } finally {
      setBusyKeyId("");
    }
  }, [refresh]);

  return {
    keys,
    loading,
    error,
    isCreating,
    busyKeyId,
    activeCount: keys.filter((item) => item.isActive).length,
    refresh,
    createKey,
    setKeyActive,
    removeKey,
  };
}
