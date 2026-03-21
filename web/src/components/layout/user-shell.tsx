import { Check, Globe2, MoonStar, Settings, SunMedium } from "lucide-react";
import { useEffect, useRef, useState } from "react";
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
  const languageMenuRef = useRef<HTMLDivElement | null>(null);
  const [isLanguageMenuOpen, setIsLanguageMenuOpen] = useState(false);

  const currentThemeLabel = theme === "dark" ? t("shell.themeDark") : t("shell.themeLight");
  const isSetupActive = location.pathname.startsWith("/setup");

  const statusDotClass = connection.tone === "ready"
    ? "bg-success"
    : connection.tone === "error"
      ? "bg-danger"
      : "bg-text-muted";

  const toolBtnClass = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-transparent bg-transparent text-text-secondary transition-colors hover:border-outline hover:bg-surface-container-low hover:text-text-primary";

  useEffect(() => {
    if (!isLanguageMenuOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      if (!languageMenuRef.current?.contains(event.target as Node)) {
        setIsLanguageMenuOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsLanguageMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isLanguageMenuOpen]);

  useEffect(() => {
    setIsLanguageMenuOpen(false);
  }, [location.pathname]);

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

          <div className="flex items-center gap-1.5">
            <div ref={languageMenuRef} className="relative">
              <button
                type="button"
                className={cn(
                  toolBtnClass,
                  isLanguageMenuOpen && "border-outline bg-surface-container-low text-text-primary",
                )}
                aria-label={t("shell.languageToggle")}
                title={t("shell.languageToggle")}
                onClick={() => setIsLanguageMenuOpen((current) => !current)}
              >
                <Globe2 className="h-4 w-4" />
              </button>
              {isLanguageMenuOpen ? (
                <div
                  className="absolute right-0 top-full z-20 mt-2 w-44 rounded-xl border border-outline bg-surface-glass p-1.5 shadow-float backdrop-blur-xl"
                  role="menu"
                  aria-label={t("shell.languageMenu")}
                >
                  {locales.map((locale) => {
                    const isSelected = language === locale.code;
                    const localeLabel = locale.code === "zh-CN"
                      ? t("shell.languages.zhCN")
                      : t("shell.languages.en");
                    return (
                      <button
                        key={locale.code}
                        type="button"
                        className={cn(
                          "flex h-9 w-full items-center justify-between rounded-lg px-2.5 text-sm transition-colors",
                          isSelected
                            ? "bg-surface-container-high text-text-primary"
                            : "text-text-secondary hover:bg-surface-container-low hover:text-text-primary",
                        )}
                        role="menuitemradio"
                        aria-checked={isSelected}
                        onClick={() => {
                          void setLanguage(locale.code);
                          setIsLanguageMenuOpen(false);
                        }}
                      >
                        <span>{localeLabel}</span>
                        {isSelected ? <Check className="h-4 w-4" /> : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>

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
