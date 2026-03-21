import type {
  ApiKeysData,
  DashboardData,
  ModelsData,
  QueueTask,
  SettingsData,
  TaskOverviewMetric,
} from "@/data/admin-mocks";
import { buildApiUrl, extractErrorMessage, getDefaultBaseUrl } from "@/lib/api";

const ADMIN_TOKEN_KEY = "cubie_admin_token";

export function getAdminToken(): string {
  return localStorage.getItem(ADMIN_TOKEN_KEY) || "";
}

export function setAdminToken(token: string) {
  localStorage.setItem(ADMIN_TOKEN_KEY, token);
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
    throw new Error(await extractErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

// Dashboard
export const fetchDashboard = () => adminFetch<DashboardData>("/api/admin/dashboard");

// Tasks
export const fetchAdminTasks = () => adminFetch<{ tasks: QueueTask[] }>("/api/admin/tasks");

export interface TasksStatsResponse {
  overview: TaskOverviewMetric[];
  countByStatus: Record<string, number>;
}
export const fetchTasksStats = () => adminFetch<TasksStatsResponse>("/api/admin/tasks/stats");

// Models
export const fetchModels = () => adminFetch<ModelsData>("/api/admin/models");
export const createModel = (data: Record<string, unknown>) =>
  adminFetch<unknown>("/api/admin/models", { method: "POST", body: JSON.stringify(data) });
export const updateModel = (id: string, data: Record<string, unknown>) =>
  adminFetch<unknown>(`/api/admin/models/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
export const deleteModel = (id: string) =>
  adminFetch<unknown>(`/api/admin/models/${encodeURIComponent(id)}`, { method: "DELETE" });

// API Keys
export const fetchAdminKeys = () => adminFetch<{ keys: ApiKeysData["keys"] }>("/api/admin/keys");

export interface KeysStatsResponse {
  total_keys: number;
  active_keys: number;
  total_requests: number;
}
export const fetchKeysStats = () => adminFetch<KeysStatsResponse>("/api/admin/keys/stats");

// Settings
export const fetchSettings = () => adminFetch<SettingsData>("/api/admin/settings");
export const updateSettings = (data: Record<string, unknown>) =>
  adminFetch<unknown>("/api/admin/settings", { method: "PATCH", body: JSON.stringify(data) });
