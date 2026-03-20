import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/i18n/en.json";
import zhCN from "@/i18n/zh-CN.json";
import { LANGUAGE_STORAGE_KEY } from "@/hooks/use-locale";

const resources = {
  en: {
    translation: en,
  },
  "zh-CN": {
    translation: zhCN,
  },
} as const;

function resolveInitialLanguage() {
  if (typeof window === "undefined") {
    return "en";
  }

  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (stored === "en" || stored === "zh-CN") {
    return stored;
  }

  return navigator.language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

if (!i18n.isInitialized) {
  void i18n
    .use(initReactI18next)
    .init({
      resources,
      lng: resolveInitialLanguage(),
      fallbackLng: "en",
      supportedLngs: ["en", "zh-CN"],
      interpolation: {
        escapeValue: false,
      },
    })
    .then(() => {
      document.documentElement.lang = i18n.resolvedLanguage ?? "en";
    });
}

export default i18n;
