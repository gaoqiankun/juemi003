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

export function formatTimestamp(locale: AdminLocale, value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat(resolveLocale(locale), {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function maskKey(prefix: string) {
  return `${prefix}••••••••••••`;
}
