import { getDefaultBaseUrl, normalizeBaseUrl } from "@/lib/api";
import { readUserConfig } from "@/lib/user-config";
import type { ApiConfig, ConnectionState, GenerateState } from "@/lib/types";

export const STORAGE_KEYS = {
  config: "app.react.config.v1",
  currentTask: "app.react.current-task.v1",
};

export const TASK_PAGE_LIMIT = 20;
export const POLL_INTERVAL_MS = 3000;

export const defaultConnectionState: ConnectionState = {
  tone: "error",
  label: "连接失败",
  detail: "服务暂不可用",
};

export const defaultGenerateState = (token = "", currentTaskId = ""): GenerateState => ({
  file: null,
  previewDataUrl: "",
  uploadedUrl: "",
  uploadId: "",
  name: "",
  callbackUrl: "",
  isUploading: false,
  uploadProgress: 0,
  isSubmitting: false,
  statusMessage: token
    ? "图片就绪后即可开始生成。"
    : "请先到设置页填写连接信息。",
  statusTone: token ? "info" : "error",
  currentTaskId,
});

export function readStoredCurrentTaskId() {
  try {
    return String(sessionStorage.getItem(STORAGE_KEYS.currentTask) || "").trim();
  } catch {
    return "";
  }
}

export function readStoredConfig(): ApiConfig {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEYS.config) || "{}");
    const legacy = readUserConfig();
    return {
      baseUrl: normalizeBaseUrl(saved.baseUrl || legacy.serverUrl || getDefaultBaseUrl()),
      token: String(saved.token || legacy.apiKey || "").trim(),
    };
  } catch {
    const legacy = readUserConfig();
    return {
      baseUrl: normalizeBaseUrl(legacy.serverUrl || getDefaultBaseUrl()),
      token: String(legacy.apiKey || "").trim(),
    };
  }
}
