const CONFIG_STORAGE_KEY = "app.react.config.v1";
export const API_KEY_STORAGE_KEY = "app-api-key";
export const SERVER_URL_STORAGE_KEY = "app-server-url";

export interface UserConfig {
  apiKey: string;
  serverUrl: string;
}

export function readUserConfig(): UserConfig {
  if (typeof window === "undefined") {
    return {
      apiKey: "",
      serverUrl: "",
    };
  }

  try {
    const saved = JSON.parse(window.localStorage.getItem(CONFIG_STORAGE_KEY) ?? "{}");
    const apiKey = String(saved.token || "").trim();
    const serverUrl = String(saved.baseUrl || "").trim();
    if (apiKey || serverUrl) {
      return {
        apiKey,
        serverUrl,
      };
    }
  } catch {
    // ignore malformed config payloads and fall back to legacy keys
  }

  return {
    apiKey: window.localStorage.getItem(API_KEY_STORAGE_KEY) ?? "",
    serverUrl: window.localStorage.getItem(SERVER_URL_STORAGE_KEY) ?? "",
  };
}

export function hasUserApiKey() {
  return readUserConfig().apiKey.trim().length > 0;
}

export function saveUserConfig(config: UserConfig) {
  const normalized = {
    apiKey: config.apiKey.trim(),
    serverUrl: config.serverUrl.trim(),
  };
  window.localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify({
    token: normalized.apiKey,
    baseUrl: normalized.serverUrl,
  }));
  window.localStorage.setItem(API_KEY_STORAGE_KEY, normalized.apiKey);
  window.localStorage.setItem(SERVER_URL_STORAGE_KEY, normalized.serverUrl);
}
