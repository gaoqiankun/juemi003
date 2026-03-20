import { Globe2, MoonStar, Settings, SunMedium } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useGen3d } from "@/app/gen3d-provider";
import { useLocale } from "@/hooks/use-locale";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

export function UserShell() {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { language, toggleLanguage } = useLocale();
  const { connection } = useGen3d();
  const location = useLocation();
  const currentThemeLabel = theme === "dark" ? t("shell.themeDark") : t("shell.themeLight");
  const currentLanguageLabel = language === "en" ? "English" : "中文";
  const toneClass = connection.tone === "ready"
    ? "bg-success-text"
    : connection.tone === "error"
      ? "bg-danger-text"
      : "bg-text-muted";
  const settingsButtonClassName = (active: boolean) => cn(
    "inline-flex h-9 w-9 items-center justify-center rounded-lg border transition-colors",
    active
      ? "border-outline bg-surface-container-highest text-text-primary"
      : "border-transparent bg-transparent text-text-secondary hover:border-outline hover:bg-surface-container-low hover:text-text-primary",
  );

  return (
    <div className="min-h-screen bg-[image:var(--page-gradient)] bg-background text-text-primary">
      <header className="sticky top-0 z-30 border-b border-outline bg-surface backdrop-blur-xl">
        <div className="mx-auto flex h-12 w-full max-w-[1560px] items-center justify-between gap-4 px-4">
          <NavLink to="/generate" className="inline-flex min-w-fit items-center gap-2 text-text-primary">
            <img
              src={`${import.meta.env.BASE_URL}favicon.svg`}
              alt="Cubie 3D"
              className="h-6 w-6 rounded-md"
            />
            <span className="text-[15px] font-semibold tracking-[0.02em]">Cubie 3D</span>
          </NavLink>

          <div className="flex items-center gap-2">
            <span
              className={cn("h-2 w-2 rounded-full", toneClass)}
              title={connection.detail}
              aria-label={connection.label}
            />

            <div className="flex items-center gap-1">
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-transparent text-text-secondary transition-colors hover:bg-surface-container-highest hover:text-text-primary"
                onClick={toggleTheme}
                aria-label={t("shell.themeToggle")}
                title={currentThemeLabel}
              >
                {theme === "dark" ? <SunMedium className="h-4 w-4" /> : <MoonStar className="h-4 w-4" />}
              </button>

              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-transparent text-text-secondary transition-colors hover:bg-surface-container-highest hover:text-text-primary"
                onClick={toggleLanguage}
                aria-label={t("shell.languageToggle")}
                title={currentLanguageLabel}
              >
                <Globe2 className="h-4 w-4" />
              </button>
            </div>

            <NavLink
              to="/setup"
              state={{ from: location.pathname }}
              className={({ isActive }) => settingsButtonClassName(isActive)}
              aria-label={t("user.shell.nav.setup")}
            >
              <Settings className="h-4 w-4" />
            </NavLink>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1560px] px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
