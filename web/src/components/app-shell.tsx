import type { ReactNode } from "react";
import { Outlet, NavLink, useLocation } from "react-router-dom";
import { Settings2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { useGen3d } from "@/app/gen3d-provider";

export function AppShell({
  children,
  activePath,
  embedded = false,
}: {
  children?: ReactNode;
  activePath?: string;
  embedded?: boolean;
}) {
  const { connection } = useGen3d();
  const location = useLocation();
  const toneClass = connection.tone === "ready"
    ? "bg-emerald-400"
    : connection.tone === "empty"
      ? "bg-slate-500"
      : "bg-rose-400";
  const connectionTitle = connection.tone === "ready"
    ? "服务正常"
    : connection.tone === "error"
      ? "连接失败"
      : "等待连接";
  const content = children ?? <Outlet />;
  const settingsButtonClassName = (active: boolean) => cn(
    "inline-flex h-8 w-8 items-center justify-center rounded-[8px] border transition",
    active
      ? "border-[#2a2a2a] bg-[#1a1a1a] text-white"
      : "border-transparent bg-transparent text-[#888888] hover:border-[#2a2a2a] hover:bg-[#111111] hover:text-white",
  );

  return (
    <div className={cn(embedded ? "min-h-full" : "min-h-screen", "bg-[#000000] text-white")}>
      <header className={cn(
        "z-40 h-12 border-b border-[#1f1f1f] bg-[#0a0a0a]",
        embedded ? "relative" : "sticky top-0",
      )}
      >
        <div className="flex h-full items-center justify-between px-4">
          <NavLink to="/" className="inline-flex items-center gap-2 text-white">
            <img src="/favicon.svg" alt="Cubify 3D" className="h-6 w-6" />
            <span className="text-[15px] font-semibold tracking-[0.02em]">Cubify 3D</span>
          </NavLink>

          <div className="flex items-center gap-3">
            <span
              className={cn("h-2 w-2 rounded-full", toneClass)}
              title={connectionTitle}
              aria-label={connectionTitle}
            />
            {activePath ? (
              <span aria-current={activePath === "/settings" ? "page" : undefined} className={settingsButtonClassName(activePath === "/settings")}>
                <Settings2 className="h-4 w-4" />
              </span>
            ) : (
              <NavLink
                to="/settings"
                state={{ from: location.pathname }}
                className={({ isActive }) => settingsButtonClassName(isActive)}
              >
                <Settings2 className="h-4 w-4" />
              </NavLink>
            )}
          </div>
        </div>
      </header>

      <main className={cn(
        "min-h-[calc(100vh-48px)]",
        embedded ? "w-full" : "w-full",
      )}
      >
        {content}
      </main>
    </div>
  );
}
