import type {
  ApiConfig,
  HealthPayload,
  TaskCreatePayload,
  TaskListPayload,
  TaskSnapshotPayload,
  UploadResponse,
  UserModelListPayload,
} from "@/lib/types";

export function getDefaultBaseUrl() {
  const origin = window.location.origin;
  if (!origin || origin === "null") {
    return "http://localhost:8000";
  }
  return origin;
}

export function normalizeBaseUrl(value?: string) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return getDefaultBaseUrl();
  }
  return trimmed.replace(/\/+$/, "");
}

function ensureTrailingSlash(url: string) {
  return url.endsWith("/") ? url : `${url}/`;
}

export function buildApiUrl(baseUrl: string, path: string) {
  return new URL(String(path).replace(/^\/+/, ""), ensureTrailingSlash(baseUrl)).toString();
}

export function authHeaders(token: string, json = false) {
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (json) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

export async function extractErrorMessage(response: Response) {
  if (response.status === 401) {
    return "API 密钥无效或已停用";
  }
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (payload.detail) {
      return JSON.stringify(payload.detail);
    }
    return JSON.stringify(payload);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

export async function fetchHealth(config: ApiConfig) {
  const response = await fetch(buildApiUrl(config.baseUrl, "/health"), {
    headers: authHeaders(config.token, false),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as HealthPayload;
}

export async function fetchModels(config: ApiConfig) {
  const response = await fetch(buildApiUrl(config.baseUrl, "/v1/models"), {
    headers: authHeaders(config.token, false),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as UserModelListPayload;
}

export async function fetchTaskList(config: ApiConfig, before = "", limit = 20) {
  const url = new URL(buildApiUrl(config.baseUrl, "/v1/tasks"));
  url.searchParams.set("limit", String(limit));
  if (before) {
    url.searchParams.set("before", before);
  }
  const response = await fetch(url.toString(), {
    headers: authHeaders(config.token, false),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as TaskListPayload;
}

export async function fetchTask(config: ApiConfig, taskId: string) {
  const response = await fetch(buildApiUrl(config.baseUrl, `/v1/tasks/${encodeURIComponent(taskId)}`), {
    headers: authHeaders(config.token, false),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as TaskSnapshotPayload;
}

export async function fetchAuthorizedBlobUrl(
  config: ApiConfig,
  path: string,
  signal?: AbortSignal,
) {
  const response = await fetch(buildApiUrl(config.baseUrl, path), {
    headers: authHeaders(config.token, false),
    cache: "no-store",
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

export async function createTask(config: ApiConfig, payload: TaskCreatePayload) {
  const response = await fetch(buildApiUrl(config.baseUrl, "/v1/tasks"), {
    method: "POST",
    headers: authHeaders(config.token, true),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as TaskSnapshotPayload;
}

export async function requestTaskCancel(config: ApiConfig, taskId: string) {
  const response = await fetch(buildApiUrl(config.baseUrl, `/v1/tasks/${encodeURIComponent(taskId)}/cancel`), {
    method: "POST",
    headers: authHeaders(config.token, false),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as TaskSnapshotPayload;
}

export async function requestTaskDelete(config: ApiConfig, taskId: string) {
  const response = await fetch(buildApiUrl(config.baseUrl, `/v1/tasks/${encodeURIComponent(taskId)}`), {
    method: "DELETE",
    headers: authHeaders(config.token, false),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
}

export function uploadFile(
  config: ApiConfig,
  file: File,
  onProgress: (progress: number) => void,
) {
  return new Promise<UploadResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", buildApiUrl(config.baseUrl, "/v1/upload"));
    Object.entries(authHeaders(config.token, false)).forEach(([key, value]) => {
      xhr.setRequestHeader(key, value);
    });
    xhr.responseType = "json";

    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) {
        return;
      }
      const percent = Math.round((event.loaded / event.total) * 100);
      onProgress(percent);
    });

    xhr.addEventListener("load", async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response || JSON.parse(xhr.responseText || "{}"));
        return;
      }
      if (xhr.status === 401) {
        reject(new Error("API 密钥无效或已停用"));
        return;
      }
      try {
        const payload = xhr.response || (xhr.responseText ? JSON.parse(xhr.responseText) : null);
        if (payload && typeof payload.detail === "string") {
          reject(new Error(payload.detail));
          return;
        }
        reject(new Error(`${xhr.status} ${xhr.statusText}`));
      } catch {
        reject(new Error(`${xhr.status} ${xhr.statusText}`));
      }
    });

    xhr.addEventListener("error", () => {
      reject(new Error("上传失败，网络连接中断"));
    });

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}
