import { Globe2, MoonStar, Settings, SunMedium } from "lucide-react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useGen3d } from "@/app/gen3d-provider";
import { useLocale } from "@/hooks/use-locale";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

export function UserShell() {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { language, setLanguage, locales } = useLocale();
  const { connection } = useGen3d();
  const location = useLocation();

  const currentThemeLabel = theme === "dark" ? t("shell.themeDark") : t("shell.themeLight");
  const isGenerateActive = location.pathname.startsWith("/generate") || location.pathname.startsWith("/setup");
  const isGalleryActive = location.pathname.startsWith("/gallery") || location.pathname.startsWith("/viewer/");
  const isSetupActive = location.pathname.startsWith("/setup");

  const statusDotClass = connection.tone === "ready"
    ? "bg-success"
    : connection.tone === "error"
      ? "bg-danger"
      : "bg-text-muted";

  const navItemClass = (active: boolean) => cn(
    "relative inline-flex h-9 items-center rounded-full px-4 text-sm font-medium transition",
    active
      ? "bg-surface-container-high text-text-primary"
      : "text-text-secondary hover:bg-surface-container-low hover:text-text-primary",
  );

  const toolBtnClass = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-transparent bg-transparent text-text-secondary transition-colors hover:border-outline hover:bg-surface-container-low hover:text-text-primary";

  return (
    <div className="min-h-screen bg-[image:var(--page-gradient)] bg-background text-text-primary">
      <header className="sticky top-0 z-40 border-b border-outline bg-surface/90 backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-[1560px] items-center justify-between gap-4 px-4 md:px-6">
          <Link to="/generate" className="inline-flex min-w-fit items-center gap-2.5 text-text-primary">
            <img
              src={`${import.meta.env.BASE_URL}favicon.svg`}
              alt="Cubie 3D"
              className="h-7 w-7 rounded-md"
            />
            <span className="text-[15px] font-semibold tracking-[0.02em]">Cubie 3D</span>
          </Link>

          <nav className="hidden items-center gap-1 rounded-full border border-outline bg-surface-container-low p-1 md:flex" aria-label={t("user.shell.navigation")}>
            <Link to="/generate" className={navItemClass(isGenerateActive)}>
              {t("user.shell.nav.generate")}
            </Link>
            <Link to="/gallery" className={navItemClass(isGalleryActive)}>
              {t("user.shell.nav.gallery")}
            </Link>
          </nav>

          <div className="flex items-center gap-1.5">
            <label className="relative inline-flex items-center">
              <Globe2 className="pointer-events-none absolute left-2 h-3.5 w-3.5 text-text-muted" />
              <select
                value={language}
                onChange={(event) => {
                  void setLanguage(event.target.value as "en" | "zh-CN");
                }}
                aria-label={t("shell.languageToggle")}
                className="h-9 rounded-lg border border-outline bg-surface-container-low pl-7 pr-6 text-xs font-medium text-text-primary outline-none transition focus:border-accent"
              >
                {locales.map((locale) => (
                  <option key={locale.code} value={locale.code}>
                    {locale.short}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className={toolBtnClass}
              onClick={toggleTheme}
              aria-label={t("shell.themeToggle")}
              title={currentThemeLabel}
            >
              {theme === "dark" ? <SunMedium className="h-4 w-4" /> : <MoonStar className="h-4 w-4" />}
            </button>

            <Link
              to="/setup"
              state={{ from: location.pathname }}
              className={cn(
                "relative inline-flex h-9 w-9 items-center justify-center rounded-lg border transition-colors",
                isSetupActive
                  ? "border-outline bg-surface-container-high text-text-primary"
                  : "border-transparent bg-transparent text-text-secondary hover:border-outline hover:bg-surface-container-low hover:text-text-primary",
              )}
              aria-label={t("user.shell.nav.setup")}
              title={connection.detail}
            >
              <Settings className="h-4 w-4" />
              <span
                className={cn("absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border border-surface", statusDotClass)}
                aria-hidden="true"
              />
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1560px] px-4 py-6 md:px-6">
        <Outlet />
      </main>
    </div>
  );
}
