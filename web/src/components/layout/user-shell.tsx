import { Globe2, MoonStar, SunMedium } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/ui/primitives";
import { useLocale } from "@/hooks/use-locale";
import { useTheme } from "@/hooks/use-theme";

const navigation = [
  { key: "generate", path: "/generate" },
  { key: "generations", path: "/generations" },
  { key: "setup", path: "/setup" },
];

export function UserShell() {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { language, toggleLanguage } = useLocale();

  return (
    <div className="user-shell">
      <header className="user-topbar">
        <div className="user-topbar-main">
          <NavLink to="/generate" className="user-brand">
            <img
              src={`${import.meta.env.BASE_URL}favicon.svg`}
              alt="Cubify 3D"
              className="brand-icon"
            />
            <div>
              <div className="eyebrow">{t("user.shell.brandEyebrow")}</div>
              <div className="brand-title">Cubify 3D</div>
            </div>
          </NavLink>

          <nav className="user-nav" aria-label={t("user.shell.navigation")}>
            {navigation.map((item) => (
              <NavLink
                key={item.key}
                to={item.path}
                className={({ isActive }) => `user-nav-item ${isActive ? "user-nav-item-active" : ""}`}
              >
                {t(`user.shell.nav.${item.key}`)}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="topbar-actions">
          <Card tone="glass" className="toolbar-panel">
            <button
              type="button"
              className="toolbar-toggle"
              onClick={toggleTheme}
              aria-label={t("shell.themeToggle")}
            >
              {theme === "dark" ? <SunMedium className="toolbar-icon" /> : <MoonStar className="toolbar-icon" />}
              <span>{theme === "dark" ? t("shell.themeLight") : t("shell.themeDark")}</span>
            </button>

            <button
              type="button"
              className="toolbar-toggle"
              onClick={toggleLanguage}
              aria-label={t("shell.languageToggle")}
            >
              <Globe2 className="toolbar-icon" />
              <span>{language === "en" ? "zh-CN" : "EN"}</span>
            </button>
          </Card>
        </div>
      </header>

      <main className="user-workspace">
        <Outlet />
      </main>
    </div>
  );
}
