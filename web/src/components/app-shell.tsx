import type { ReactNode } from "react";
import { Globe2, MoonStar, Settings2, SunMedium } from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useGen3d } from "@/app/gen3d-provider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLocale } from "@/hooks/use-locale";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

export function AppShell({
  children,
  activePath,
  embedded = false,
}: {
  children?: ReactNode;
  activePath?: string;
  embedded?: boolean;
}) {
  const { t } = useTranslation();
  const { connection } = useGen3d();
  const { theme, toggleTheme } = useTheme();
  const { language, setLanguage, locales } = useLocale();
  const location = useLocation();
  const content = children ?? <Outlet />;

  const currentThemeLabel = theme === "dark" ? t("shell.themeDark") : t("shell.themeLight");
  const previewPath = activePath === "/" ? "/generate" : activePath;
  const currentPath = previewPath || location.pathname;
  const isGenerateActive = currentPath.startsWith("/generate") || currentPath.startsWith("/setup");
  const isGalleryActive = currentPath.startsWith("/gallery") || currentPath.startsWith("/viewer/");

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

  const settingsButtonClassName = (active: boolean) => cn(
    "relative inline-flex h-9 w-9 items-center justify-center rounded-lg border transition",
    active
      ? "border-outline bg-surface-container-high text-text-primary"
      : "border-transparent bg-transparent text-text-secondary hover:border-outline hover:bg-surface-container-low hover:text-text-primary",
  );

  return (
    <div className={cn(embedded ? "min-h-full" : "min-h-screen", "bg-[image:var(--page-gradient)] bg-background text-text-primary")}>
      <header className={cn(
        "z-40 h-16 border-b border-outline bg-surface/90 backdrop-blur-xl",
        embedded ? "relative" : "sticky top-0",
      )}
      >
        <div className="mx-auto flex h-full w-full max-w-[1560px] items-center justify-between gap-4 px-4 md:px-6">
          <Link to="/generate" className="inline-flex min-w-fit items-center gap-2.5 text-text-primary">
            <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="Cubie 3D" className="h-7 w-7 rounded-md" />
            <span className="text-[15px] font-semibold tracking-[0.02em]">Cubie 3D</span>
          </Link>

          <nav className="hidden items-center gap-1 rounded-full border border-outline bg-surface-container-low p-1 md:flex" aria-label={t("user.shell.navigation")}>
            {activePath ? (
              <>
                <span className={navItemClass(isGenerateActive)}>{t("user.shell.nav.generate")}</span>
                <span className={navItemClass(isGalleryActive)}>{t("user.shell.nav.gallery")}</span>
              </>
            ) : (
              <>
                <NavLink to="/generate" className={({ isActive }) => navItemClass(isActive)}>{t("user.shell.nav.generate")}</NavLink>
                <NavLink to="/gallery" className={({ isActive }) => navItemClass(isActive)}>{t("user.shell.nav.gallery")}</NavLink>
              </>
            )}
          </nav>

          <div className="flex items-center gap-1.5">
            <div className="relative">
              <Globe2 className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
              <Select
                value={language}
                onValueChange={(nextValue) => {
                  void setLanguage(nextValue as "en" | "zh-CN");
                }}
              >
                <SelectTrigger aria-label={t("shell.languageToggle")} className="h-9 w-[5.25rem] rounded-lg border-outline bg-surface-container-low pl-7 pr-2 text-xs font-medium">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {locales.map((locale) => (
                    <SelectItem key={locale.code} value={locale.code}>
                      {locale.short}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <button
              type="button"
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-transparent bg-transparent text-text-secondary transition-colors hover:border-outline hover:bg-surface-container-low hover:text-text-primary"
              onClick={toggleTheme}
              aria-label={t("shell.themeToggle")}
              title={currentThemeLabel}
            >
              {theme === "dark" ? <SunMedium className="h-4 w-4" /> : <MoonStar className="h-4 w-4" />}
            </button>

            {activePath ? (
              <span className={settingsButtonClassName(activePath === "/setup")}>
                <Settings2 className="h-4 w-4" />
                <span
                  className={cn("absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border border-surface", statusDotClass)}
                  aria-hidden="true"
                />
              </span>
            ) : (
              <NavLink
                to="/setup"
                state={{ from: location.pathname }}
                className={({ isActive }) => settingsButtonClassName(isActive)}
              >
                <Settings2 className="h-4 w-4" />
                <span
                  className={cn("absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border border-surface", statusDotClass)}
                  aria-hidden="true"
                />
              </NavLink>
            )}
          </div>
        </div>
      </header>

      <main className="min-h-[calc(100vh-64px)] w-full">
        {content}
      </main>
    </div>
  );
}
