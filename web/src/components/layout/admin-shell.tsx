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

import { useLocale } from "@/hooks/use-locale";
import { useTheme } from "@/hooks/use-theme";
import { Button, Card } from "@/components/ui/primitives";

const navigation = [
  { key: "dashboard", path: "/admin/dashboard", icon: LayoutDashboard },
  { key: "tasks", path: "/admin/tasks", icon: Workflow },
  { key: "models", path: "/admin/models", icon: Boxes },
  { key: "apiKeys", path: "/admin/api-keys", icon: KeyRound },
  { key: "settings", path: "/admin/settings", icon: Settings2 },
];

export function AdminShell() {
  const location = useLocation();
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { language, toggleLanguage } = useLocale();

  const activeItem = navigation.find((item) => location.pathname.startsWith(item.path))
    ?? navigation[0];

  return (
    <div className="admin-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-lockup">
            <img
              src={`${import.meta.env.BASE_URL}favicon.svg`}
              alt="Cubify 3D"
              className="brand-icon"
            />
            <div>
              <div className="eyebrow">{t("shell.brandEyebrow")}</div>
              <div className="brand-title">Cubify 3D</div>
            </div>
          </div>
          <p className="sidebar-copy">{t("shell.brandCopy")}</p>
        </div>

        <nav className="sidebar-nav" aria-label={t("shell.navigation")}>
          {navigation.map((item) => {
            const Icon = item.icon;

            return (
              <NavLink
                key={item.key}
                to={item.path}
                className={({ isActive }) => clsx("nav-item", { "nav-item-active": isActive })}
              >
                <Icon className="nav-item-icon" />
                <span>{t(`shell.nav.${item.key}`)}</span>
              </NavLink>
            );
          })}
        </nav>

        <Card tone="muted" className="sidebar-footnote">
          <div className="eyebrow">{t("shell.deployLabel")}</div>
          <div className="sidebar-footnote-title">{t("shell.deployValue")}</div>
          <p className="sidebar-copy">{t("shell.deployCopy")}</p>
        </Card>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">{t("shell.navigation")}</div>
            <h1 className="topbar-title">{t(`shell.nav.${activeItem.key}`)}</h1>
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

            <Button variant="primary" className="topbar-pill">
              {t("shell.environment")}
            </Button>
          </div>
        </header>

        <main className="workspace-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
