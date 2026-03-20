export const API_KEY_STORAGE_KEY = "cubify3d-api-key";
export const SERVER_URL_STORAGE_KEY = "cubify3d-server-url";

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

  return {
    apiKey: window.localStorage.getItem(API_KEY_STORAGE_KEY) ?? "",
    serverUrl: window.localStorage.getItem(SERVER_URL_STORAGE_KEY) ?? "",
  };
}

export function hasUserApiKey() {
  return readUserConfig().apiKey.trim().length > 0;
}

export function saveUserConfig(config: UserConfig) {
  window.localStorage.setItem(API_KEY_STORAGE_KEY, config.apiKey.trim());
  window.localStorage.setItem(SERVER_URL_STORAGE_KEY, config.serverUrl.trim());
}
