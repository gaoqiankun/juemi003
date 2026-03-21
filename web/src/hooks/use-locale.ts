import { useTranslation } from "react-i18next";

import type { AdminLocale } from "@/data/admin-mocks";

export const LANGUAGE_STORAGE_KEY = "app-admin-language";
export const LOCALE_OPTIONS: Array<{ code: AdminLocale; short: string }> = [
  { code: "en", short: "EN" },
  { code: "zh-CN", short: "中" },
];

export function useLocale() {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en";

  const setLanguage = async (nextLanguage: AdminLocale) => {
    await i18n.changeLanguage(nextLanguage);
    document.documentElement.lang = nextLanguage;
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, nextLanguage);
  };

  const toggleLanguage = async () => {
    await setLanguage(language === "en" ? "zh-CN" : "en");
  };

  return {
    language: language as AdminLocale,
    setLanguage,
    toggleLanguage,
    locales: LOCALE_OPTIONS,
  };
}
