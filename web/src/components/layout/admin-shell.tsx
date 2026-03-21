import clsx from "clsx";
import {
  Boxes,
  Globe2,
  KeyRound,
  LayoutDashboard,
  MoonStar,
  Settings2,
  SunMedium,
  Workflow,
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useGen3d } from "@/app/gen3d-provider";
import { Card } from "@/components/ui/primitives";
import { useLocale } from "@/hooks/use-locale";
import { useTheme } from "@/hooks/use-theme";

const navigation = [
  { key: "dashboard", path: "/admin/dashboard", icon: LayoutDashboard },
  { key: "tasks", path: "/admin/tasks", icon: Workflow },
  { key: "models", path: "/admin/models", icon: Boxes },
  { key: "apiKeys", path: "/admin/api-keys", icon: KeyRound },
  { key: "settings", path: "/admin/settings", icon: Settings2 },
];

const metaClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";

export function AdminShell() {
  const location = useLocation();
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { language, toggleLanguage } = useLocale();
  const { connection } = useGen3d();
  const currentThemeLabel = theme === "dark" ? t("shell.themeDark") : t("shell.themeLight");
  const currentLanguageLabel = language === "en" ? "English" : "中文";
  const toneClass = connection.tone === "ready"
    ? "bg-success-text"
    : connection.tone === "error"
      ? "bg-danger-text"
      : "bg-text-muted";

  const activeItem = navigation.find((item) => location.pathname.startsWith(item.path))
    ?? navigation[0];

  return (
    <div className="min-h-screen bg-[image:var(--page-gradient)] bg-background text-text-primary lg:grid lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="border-b border-outline bg-surface backdrop-blur-xl lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
        <div className="flex h-full flex-col gap-6 px-6 py-8">
          <div className="grid gap-4">
            <div className="flex items-center gap-3">
              <img
                src={`${import.meta.env.BASE_URL}favicon.svg`}
                alt="Cubie"
                className="h-11 w-11 rounded-xl border border-outline bg-surface-container-low p-1.5"
              />
              <div className="min-w-0">
                <div className={metaClassName}>{t("shell.brandEyebrow")}</div>
                <div className="mt-1 text-xl font-semibold tracking-[-0.03em] text-text-primary">
                  Cubie
                </div>
              </div>
            </div>
          </div>

          <nav className="grid gap-1.5" aria-label={t("shell.navigation")}>
            {navigation.map((item) => {
              const Icon = item.icon;

              return (
                <NavLink
                  key={item.key}
                  to={item.path}
                  className={({ isActive }) => clsx(
                    "inline-flex items-center gap-3 rounded-xl border px-4 py-3 text-sm font-medium transition-all duration-200",
                    isActive
                      ? "border-outline bg-surface-container-highest text-text-primary shadow-float"
                      : "border-transparent bg-transparent text-text-secondary hover:border-outline hover:bg-surface-container-low hover:text-text-primary",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span>{t(`shell.nav.${item.key}`)}</span>
                </NavLink>
              );
            })}
          </nav>

          <Card tone="low" className="mt-auto grid gap-3 p-4">
            <div className={metaClassName}>{t("shell.deployLabel")}</div>
            <div className="text-lg font-semibold tracking-[-0.03em] text-text-primary">
              {t("shell.deployValue")}
            </div>
          </Card>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 border-b border-outline bg-surface backdrop-blur-xl">
          <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4 px-6 py-5 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className={metaClassName}>{t("shell.navigation")}</div>
              <h1 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-text-primary">
                {t(`shell.nav.${activeItem.key}`)}
              </h1>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1">
                <span
                  className={clsx("mx-1 h-2 w-2 rounded-full", toneClass)}
                  title={connection.detail}
                  aria-label={connection.label}
                />

                <button
                  type="button"
                  className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-transparent text-text-secondary transition-colors hover:bg-surface-container-highest hover:text-text-primary"
                  onClick={toggleTheme}
                  aria-label={t("shell.themeToggle")}
                  title={currentThemeLabel}
                >
                  {theme === "dark" ? <SunMedium className="h-4 w-4" /> : <MoonStar className="h-4 w-4" />}
                </button>

                <button
                  type="button"
                  className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-transparent text-text-secondary transition-colors hover:bg-surface-container-highest hover:text-text-primary"
                  onClick={toggleLanguage}
                  aria-label={t("shell.languageToggle")}
                  title={currentLanguageLabel}
                >
                  <Globe2 className="h-4 w-4" />
                </button>

                <NavLink
                  to="/admin/settings"
                  className={({ isActive }) => clsx(
                    "inline-flex h-10 w-10 items-center justify-center rounded-lg transition-colors",
                    isActive
                      ? "bg-surface-container-highest text-text-primary"
                      : "text-text-secondary hover:bg-surface-container-highest hover:text-text-primary",
                  )}
                  aria-label={t("shell.nav.settings")}
                  title={t("shell.nav.settings")}
                >
                  <Settings2 className="h-4 w-4" />
                </NavLink>
              </div>
            </div>
          </div>
        </header>

        <main className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
