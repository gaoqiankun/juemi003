import type { AdminLocale } from "@/data/admin-mocks";

function resolveLocale(locale: AdminLocale) {
  return locale === "zh-CN" ? "zh-CN" : "en-US";
}

export function formatCompactNumber(locale: AdminLocale, value: number) {
  return new Intl.NumberFormat(resolveLocale(locale), {
    notation: "compact",
    maximumFractionDigits: value >= 100 ? 0 : 1,
  }).format(value);
}

export function formatNumber(locale: AdminLocale, value: number, maximumFractionDigits = 0) {
  return new Intl.NumberFormat(resolveLocale(locale), {
    maximumFractionDigits,
  }).format(value);
}

export function formatCurrency(locale: AdminLocale, value: number) {
  return new Intl.NumberFormat(resolveLocale(locale), {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatPercent(locale: AdminLocale, value: number, maximumFractionDigits = 0) {
  return `${formatNumber(locale, value, maximumFractionDigits)}%`;
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

export function formatTimestamp(_locale: AdminLocale, value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  const year = date.getFullYear();
  const month = pad2(date.getMonth() + 1);
  const day = pad2(date.getDate());
  const hours = pad2(date.getHours());
  const minutes = pad2(date.getMinutes());
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

export function maskKey(prefix: string) {
  return `${prefix}••••••••••••`;
}
