import clsx from "clsx";
import {
  Boxes,
  Check,
  Languages,
  KeyRound,
  LogOut,
  MoonStar,
  Settings2,
  SunMedium,
  Workflow,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useGen3d } from "@/app/gen3d-provider";
import { Button, Card, TextField } from "@/components/ui/primitives";
import { useLocale } from "@/hooks/use-locale";
import { useTheme } from "@/hooks/use-theme";
import {
  ADMIN_AUTH_INVALID_EVENT,
  clearAdminToken,
  getAdminToken,
  setAdminToken,
  verifyAdminToken,
  type AdminApiError,
} from "@/lib/admin-api";

const navigation = [
  { key: "tasks", path: "/admin/tasks", icon: Workflow },
  { key: "models", path: "/admin/models", icon: Boxes },
  { key: "apiKeys", path: "/admin/api-keys", icon: KeyRound },
  { key: "settings", path: "/admin/settings", icon: Settings2 },
];

const metaClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";

export function AdminShell() {
  const location = useLocation();
  const { t, i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { language, locales, setLanguage } = useLocale();
  const { connection } = useGen3d();
  const languageMenuRef = useRef<HTMLDivElement | null>(null);
  const [authState, setAuthState] = useState<"checking" | "ready" | "needs_token">("checking");
  const [authTokenInput, setAuthTokenInput] = useState(() => getAdminToken());
  const [authError, setAuthError] = useState("");
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);
  const [isLanguageMenuOpen, setIsLanguageMenuOpen] = useState(false);
  const currentThemeLabel = theme === "dark" ? t("shell.themeDark") : t("shell.themeLight");
  const toneClass = connection.tone === "ready"
    ? "bg-success-text"
    : connection.tone === "error"
      ? "bg-danger-text"
      : "bg-text-muted";

  const activeItem = navigation.find((item) => location.pathname.startsWith(item.path))
    ?? navigation[0];

  const setNeedsTokenState = useCallback((message = "") => {
    setAuthState("needs_token");
    setAuthError(message);
  }, []);

  const validateStoredAdminToken = useCallback(async (
    token: string,
    copy: { invalidToken: string; unreachable: string },
  ) => {
    const normalizedToken = String(token || "").trim();
    if (!normalizedToken) {
      setNeedsTokenState("");
      return;
    }

    setAuthState("checking");
    setAuthError("");
    try {
      await verifyAdminToken(normalizedToken);
      setAuthState("ready");
    } catch (error) {
      const adminError = error as AdminApiError;
      clearAdminToken();
      if (adminError.status === 401) {
        setNeedsTokenState(copy.invalidToken);
      } else {
        setNeedsTokenState(adminError.message || copy.unreachable);
      }
    }
  }, [setNeedsTokenState]);

  useEffect(() => {
    const storedToken = getAdminToken();
    setAuthTokenInput(storedToken);
    validateStoredAdminToken(storedToken, {
      invalidToken: i18n.t("shell.adminAuth.invalidToken"),
      unreachable: i18n.t("shell.adminAuth.unreachable"),
    }).catch(() => undefined);
  }, [i18n, validateStoredAdminToken]);

  useEffect(() => {
    const handleAuthInvalid = () => {
      clearAdminToken();
      setAuthTokenInput("");
      setNeedsTokenState(t("shell.adminAuth.invalidToken"));
    };
    window.addEventListener(ADMIN_AUTH_INVALID_EVENT, handleAuthInvalid);
    return () => {
      window.removeEventListener(ADMIN_AUTH_INVALID_EVENT, handleAuthInvalid);
    };
  }, [setNeedsTokenState, t]);

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

  const handleAdminTokenSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmittingAuth) {
      return;
    }
    const nextToken = String(authTokenInput || "").trim();
    if (!nextToken) {
      setNeedsTokenState(t("shell.adminAuth.missingToken"));
      return;
    }
    setIsSubmittingAuth(true);
    setAuthState("checking");
    setAuthError("");
    try {
      await verifyAdminToken(nextToken);
      setAdminToken(nextToken);
      setAuthState("ready");
    } catch (error) {
      const adminError = error as AdminApiError;
      clearAdminToken();
      if (adminError.status === 401) {
        setNeedsTokenState(t("shell.adminAuth.invalidToken"));
      } else {
        setNeedsTokenState(adminError.message || t("shell.adminAuth.unreachable"));
      }
    } finally {
      setIsSubmittingAuth(false);
    }
  }, [authTokenInput, isSubmittingAuth, setNeedsTokenState, t]);

  const handleSignOut = useCallback(() => {
    clearAdminToken();
    setAuthTokenInput("");
    setIsLanguageMenuOpen(false);
    setNeedsTokenState("");
  }, [setNeedsTokenState]);

  if (authState !== "ready") {
    return (
      <div className="min-h-screen bg-[image:var(--page-gradient)] bg-background px-6 py-10 text-text-primary">
        <div className="mx-auto flex min-h-[70vh] w-full max-w-[420px] items-center justify-center">
          <Card className="w-full space-y-5 p-6">
            <div className="space-y-2">
              <div className={metaClassName}>{t("shell.adminAuth.title")}</div>
              <h1 className="text-2xl font-semibold tracking-[-0.03em] text-text-primary">
                {t("shell.adminAuth.heading")}
              </h1>
              <p className="text-sm text-text-secondary">{t("shell.adminAuth.copy")}</p>
            </div>

            <form className="grid gap-3" onSubmit={handleAdminTokenSubmit}>
              <label className="grid gap-1.5 text-sm text-text-secondary" htmlFor="admin-token-input">
                <span>{t("shell.adminAuth.tokenLabel")}</span>
                <TextField
                  id="admin-token-input"
                  type="password"
                  value={authTokenInput}
                  autoComplete="off"
                  placeholder={t("shell.adminAuth.tokenPlaceholder")}
                  onChange={(event) => setAuthTokenInput(event.target.value)}
                />
              </label>
              <Button type="submit" variant="primary" disabled={isSubmittingAuth || authState === "checking"}>
                {authState === "checking" ? t("shell.adminAuth.verifying") : t("shell.adminAuth.submit")}
              </Button>
            </form>

            {authError ? (
              <p className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger-text">
                {authError}
              </p>
            ) : null}
          </Card>
        </div>
      </div>
    );
  }

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
                <div className="text-xl font-semibold tracking-[-0.03em] text-text-primary">
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

          <div className="mt-auto pt-2">
            <button
              type="button"
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-outline bg-surface-container-low px-4 py-2.5 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-container hover:text-text-primary"
              onClick={handleSignOut}
            >
              <LogOut className="h-4 w-4" />
              <span>{t("shell.adminAuth.signOut")}</span>
            </button>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 border-b border-outline bg-surface backdrop-blur-xl">
          <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4 px-6 py-5 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-[-0.03em] text-text-primary">
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

                <div ref={languageMenuRef} className="relative">
                  <button
                    type="button"
                    className={clsx(
                      "inline-flex h-10 w-10 items-center justify-center rounded-lg bg-transparent text-text-secondary transition-colors hover:bg-surface-container-highest hover:text-text-primary",
                      isLanguageMenuOpen && "bg-surface-container-highest text-text-primary",
                    )}
                    onClick={() => setIsLanguageMenuOpen((current) => !current)}
                    aria-label={t("shell.languageToggle")}
                    title={t("shell.languageToggle")}
                  >
                    <Languages className="h-4 w-4" />
                  </button>
                  {isLanguageMenuOpen ? (
                    <div
                      className="absolute right-0 top-full z-20 mt-2 w-44 rounded-xl border border-outline bg-surface-glass p-1.5 shadow-float backdrop-blur-xl"
                      role="menu"
                      aria-label={t("shell.languageMenu")}
                    >
                      {locales.map((locale) => {
                        const isSelected = language === locale.code;
                        return (
                          <button
                            key={locale.code}
                            type="button"
                            className={clsx(
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
                            <span>{locale.nativeName}</span>
                            {isSelected ? <Check className="h-4 w-4" /> : null}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                </div>

                <button
                  type="button"
                  className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-transparent text-text-secondary transition-colors hover:bg-surface-container-highest hover:text-text-primary"
                  onClick={toggleTheme}
                  aria-label={t("shell.themeToggle")}
                  title={currentThemeLabel}
                >
                  {theme === "dark" ? <SunMedium className="h-4 w-4" /> : <MoonStar className="h-4 w-4" />}
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
