import type {
  SettingsData as MockSettingsData,
  TaskOverviewMetric,
} from "@/data/admin-mocks";
import { buildApiUrl, extractErrorMessage, getDefaultBaseUrl } from "@/lib/api";

const ADMIN_TOKEN_KEY = "cubie_admin_token";
export const ADMIN_AUTH_INVALID_EVENT = "cubie-admin-auth-invalid";

export interface AdminApiError extends Error {
  status?: number;
}

export interface GpuDeviceSetting {
  deviceId: string;
  enabled: boolean;
  name?: string | null;
  totalMemoryGb?: number | null;
}

export interface SettingsData extends MockSettingsData {
  gpuDevices?: GpuDeviceSetting[];
}

export function getAdminToken(): string {
  return localStorage.getItem(ADMIN_TOKEN_KEY) || "";
}

export function setAdminToken(token: string) {
  localStorage.setItem(ADMIN_TOKEN_KEY, String(token || "").trim());
}

export function clearAdminToken() {
  localStorage.removeItem(ADMIN_TOKEN_KEY);
}

function buildAdminError(response: Response, message: string): AdminApiError {
  const error = new Error(message) as AdminApiError;
  error.status = response.status;
  return error;
}

async function adminFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAdminToken();
  const baseUrl = getDefaultBaseUrl();
  const url = buildApiUrl(baseUrl, path);

  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const message = await extractErrorMessage(response);
    if (response.status === 401) {
      clearAdminToken();
      window.dispatchEvent(new CustomEvent(ADMIN_AUTH_INVALID_EVENT));
    }
    throw buildAdminError(response, message);
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  const bodyText = await response.text();
  if (!bodyText.trim()) {
    return undefined as T;
  }

  return JSON.parse(bodyText) as T;
}

export async function verifyAdminToken(token: string) {
  const normalizedToken = String(token || "").trim();
  if (!normalizedToken) {
    const missingTokenError = new Error("missing admin token") as AdminApiError;
    missingTokenError.status = 401;
    throw missingTokenError;
  }
  const response = await fetch(buildApiUrl(getDefaultBaseUrl(), "/api/admin/dashboard"), {
    headers: {
      Authorization: `Bearer ${normalizedToken}`,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    throw buildAdminError(response, await extractErrorMessage(response));
  }
}

// Tasks
export interface RawAdminTaskSummary {
  taskId?: string;
  task_id?: string;
  status?: string;
  model?: string;
  createdAt?: string;
  created_at?: string;
  finishedAt?: string | null;
  finished_at?: string | null;
  keyId?: string;
  key_id?: string;
  keyLabel?: string;
  key_label?: string;
  owner?: string;
}

export interface RawAdminTasksResponse {
  items?: RawAdminTaskSummary[];
  tasks?: RawAdminTaskSummary[];
}

export const fetchAdminTasks = () => adminFetch<RawAdminTasksResponse>("/api/admin/tasks");

export interface TasksStatsResponse {
  overview: TaskOverviewMetric[];
  countByStatus: Record<string, number>;
}
export const fetchTasksStats = () => adminFetch<TasksStatsResponse>("/api/admin/tasks/stats");

// Models
export interface RawAdminModelRecord {
  id?: string;
  providerType?: string;
  provider_type?: string;
  display_name?: string;
  model_path?: string;
  is_enabled?: boolean;
  is_default?: boolean;
  min_vram_mb?: number;
  vram_gb?: number | null;
  runtimeState?: string;
  runtime_state?: string;
  tasks_processed?: number;
  maxTasksPerSlot?: number;
  max_tasks_per_slot?: number;
  error_message?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  // Weight manager fields
  weight_source?: string;
  download_status?: string;
  download_progress?: number;
  download_speed_bps?: number;
  download_error?: string | null;
  resolvedPath?: string | null;
  resolved_path?: string | null;
  deps?: RawDepStatus[] | null;
}

export interface RawAdminModelsResponse {
  models?: RawAdminModelRecord[];
}

export type DepDownloadStatus = "done" | "downloading" | "error" | "pending";

export interface DepInstance {
  id: string;
  dep_type: string;
  hf_repo_id: string;
  display_name: string;
  weight_source: "huggingface" | "local" | "url";
  dep_model_path?: string;
  download_status: DepDownloadStatus;
  download_progress: number;
  download_speed_bps: number;
  resolved_path?: string;
  download_error?: string;
}

export interface ProviderDepType {
  dep_type: string;
  hf_repo_id: string;
  description: string;
  instances: DepInstance[];
}

export interface DepAssignment {
  instance_id?: string;
  new?: {
    instance_id: string;
    display_name: string;
    weight_source: "huggingface" | "local" | "url";
    dep_model_path: string;
  };
}

export interface RawDepStatus {
  dep_id?: string;
  instance_id?: string;
  dep_type?: string;
  display_name?: string;
  hf_repo_id?: string;
  description?: string | null;
  resolved_path?: string | null;
  download_status?: string;
  download_progress?: number;
  download_speed_bps?: number;
  download_error?: string | null;
}

export interface DepStatus {
  dep_id: string;
  hf_repo_id: string;
  description?: string;
  resolved_path?: string;
  download_status: DepDownloadStatus;
  download_progress: number;
  download_speed_bps: number;
  download_error?: string;
}

function normalizeDepDownloadStatus(status: string | undefined): DepDownloadStatus {
  const normalized = String(status || "pending").trim().toLowerCase();
  if (
    normalized === "done"
    || normalized === "downloading"
    || normalized === "error"
    || normalized === "pending"
  ) {
    return normalized;
  }
  return "pending";
}

export function normalizeDepStatus(item: RawDepStatus): DepStatus {
  const depId = String(item.dep_id || "").trim();
  const hfRepoId = String(item.hf_repo_id || "").trim();
  const description = String(item.description || "").trim();
  const resolvedPath = String(item.resolved_path || "").trim();
  const downloadError = String(item.download_error || "").trim();

  return {
    dep_id: depId,
    hf_repo_id: hfRepoId,
    ...(description ? { description } : {}),
    ...(resolvedPath ? { resolved_path: resolvedPath } : {}),
    download_status: normalizeDepDownloadStatus(item.download_status),
    download_progress: Number(item.download_progress ?? 0),
    download_speed_bps: Number(item.download_speed_bps ?? 0),
    ...(downloadError ? { download_error: downloadError } : {}),
  };
}

export const fetchModels = (includePending = false) =>
  adminFetch<RawAdminModelsResponse>(
    includePending ? "/api/admin/models?include_pending=true" : "/api/admin/models",
  );
export const fetchProviderDeps = (providerType: string): Promise<ProviderDepType[]> =>
  adminFetch<ProviderDepType[]>(
    `/api/admin/providers/${encodeURIComponent(providerType)}/deps`,
  );
export async function fetchModelDeps(modelId: string): Promise<DepStatus[]> {
  const response = await adminFetch<RawDepStatus[] | { deps?: RawDepStatus[] }>(
    `/api/admin/models/${encodeURIComponent(modelId)}/deps`,
  );
  const items = Array.isArray(response)
    ? response
    : Array.isArray(response?.deps)
      ? response.deps
      : [];
  return items.map(normalizeDepStatus);
}
export const createModel = (data: Record<string, unknown>) =>
  adminFetch<unknown>("/api/admin/models", { method: "POST", body: JSON.stringify(data) });
export const updateModel = (id: string, data: Record<string, unknown>) =>
  adminFetch<unknown>(`/api/admin/models/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
export const loadModel = (id: string) =>
  adminFetch<unknown>(`/api/admin/models/${encodeURIComponent(id)}/load`, {
    method: "POST",
  });
export const deleteModel = (id: string) =>
  adminFetch<unknown>(`/api/admin/models/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

// API Keys
export interface RawAdminKeyItem {
  keyId?: string;
  key_id?: string;
  label?: string;
  createdAt?: string;
  created_at?: string;
  isActive?: boolean;
  is_active?: boolean;
  requests?: number;
  scopes?: string[];
  owner?: string;
  lastUsedAt?: string;
  last_used_at?: string;
}

export const fetchAdminKeys = () => adminFetch<RawAdminKeyItem[] | { keys?: RawAdminKeyItem[] }>("/api/admin/keys");
export const createAdminKey = (label: string) =>
  adminFetch<{ keyId: string; token: string; label: string; createdAt: string }>("/api/admin/keys", {
    method: "POST",
    body: JSON.stringify({ label }),
  });
export const setAdminKeyActive = (keyId: string, isActive: boolean) =>
  adminFetch<RawAdminKeyItem>(`/api/admin/keys/${encodeURIComponent(keyId)}`, {
    method: "PATCH",
    body: JSON.stringify({ isActive }),
  });
export const deleteAdminKey = (keyId: string) =>
  adminFetch<unknown>(`/api/admin/keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
  });

export interface KeysStatsResponse {
  total_keys: number;
  active_keys: number;
  total_requests: number;
}
export const fetchKeysStats = () => adminFetch<KeysStatsResponse>("/api/admin/keys/stats");

// Storage
export interface StorageStats {
  disk_free_bytes: number;
  disk_total_bytes: number;
  cache_bytes: number;
  orphan_bytes: number;
  orphan_count: number;
}

export interface OrphanEntry {
  path: string;
  size_bytes: number;
}

export interface StorageBreakdownEntry {
  path: string;
  size_bytes: number;
  label: string | null;
  kind: "model" | "dep" | "residual";
}

export interface StorageBreakdown {
  entries: StorageBreakdownEntry[];
}

export const getStorageStats = () => adminFetch<StorageStats>("/api/admin/storage/stats");
export const listOrphans = () => adminFetch<OrphanEntry[]>("/api/admin/storage/orphans");
export const getStorageBreakdown = () => adminFetch<StorageBreakdown>("/api/admin/storage/breakdown");
export const cleanOrphans = () =>
  adminFetch<{ freed_bytes: number; count: number }>("/api/admin/storage/orphans", {
    method: "DELETE",
  });

// Settings
export const fetchSettings = () => adminFetch<SettingsData>("/api/admin/settings");
export interface UpdateSettingsPayload extends Record<string, unknown> {
  gpuDisabledDevices?: string[];
}

export const updateSettings = (data: UpdateSettingsPayload) =>
  adminFetch<unknown>("/api/admin/settings", { method: "PATCH", body: JSON.stringify(data) });

// HuggingFace
export interface HfStatusResponse {
  logged_in: boolean;
  username: string | null;
  endpoint: string;
}

export interface HfEndpointResponse {
  endpoint: string;
}

export const fetchHfStatus = () => adminFetch<HfStatusResponse>("/api/admin/hf-status");
export const updateHfEndpoint = (endpoint: string) =>
  adminFetch<HfEndpointResponse>("/api/admin/hf-endpoint", {
    method: "PATCH",
    body: JSON.stringify({ endpoint }),
  });
export const connectHf = (token: string) =>
  adminFetch<HfStatusResponse>("/api/admin/hf-login", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
export const disconnectHf = () =>
  adminFetch<HfStatusResponse>("/api/admin/hf-logout", {
    method: "POST",
  });
