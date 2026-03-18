import { Outlet, NavLink } from "react-router-dom";
import { GalleryHorizontalEnd, Layers3, SlidersHorizontal, Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import { useGen3d } from "@/app/gen3d-provider";

const navItems = [
  { to: "/", label: "生成", icon: Sparkles },
  { to: "/gallery", label: "图库", icon: GalleryHorizontalEnd },
  { to: "/settings", label: "设置", icon: SlidersHorizontal },
];

export function AppShell() {
  const { connection, config } = useGen3d();
  const toneClass = connection.tone === "ready"
    ? "bg-emerald-400 shadow-[0_0_0_8px_rgba(74,222,128,0.14)]"
    : connection.tone === "empty"
      ? "bg-slate-500"
      : "bg-rose-400 shadow-[0_0_0_8px_rgba(251,113,133,0.1)]";

  return (
    <div className="relative min-h-screen overflow-hidden bg-mesh text-foreground">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.18),transparent_32%),radial-gradient(circle_at_bottom_right,rgba(249,115,22,0.16),transparent_26%)]" />
      <div className="pointer-events-none absolute -left-24 top-24 h-72 w-72 rounded-full bg-cyan-500/10 blur-[120px]" />
      <div className="pointer-events-none absolute right-0 top-0 h-96 w-96 rounded-full bg-orange-500/10 blur-[160px]" />

      <header className="sticky top-0 z-40 border-b border-white/6 bg-[rgba(4,7,15,0.72)] backdrop-blur-xl">
        <div className="container flex items-center justify-between gap-4 py-4">
          <NavLink to="/" className="inline-flex items-center gap-4 rounded-full border border-white/10 bg-white/5 px-4 py-2.5 shadow-halo">
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[linear-gradient(135deg,#22d3ee,#f97316)] text-slate-950 shadow-[0_12px_30px_rgba(34,211,238,0.24)]">
              <Layers3 className="h-5 w-5" />
            </span>
            <span>
              <span className="block font-display text-sm font-semibold uppercase tracking-[0.26em] text-slate-300">gen3d</span>
              <span className="block text-sm text-slate-400">Studio Operator</span>
            </span>
          </NavLink>

          <nav className="hidden items-center gap-2 md:flex">
            {navItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) => cn(
                  "inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium transition",
                  isActive
                    ? "border-cyan-400/25 bg-white text-slate-950"
                    : "border-white/10 bg-white/5 text-slate-300 hover:border-white/15 hover:bg-white/10",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="hidden items-center gap-3 rounded-full border border-white/10 bg-white/5 px-4 py-2.5 shadow-halo sm:flex">
            <span className={cn("h-2.5 w-2.5 rounded-full", toneClass)} />
            <div className="text-right">
              <div className="text-sm font-medium text-white">{connection.tone === "ready" ? "服务连接正常" : config.token ? "等待服务响应" : "未配置 API Key"}</div>
              <div className="text-xs text-slate-400">{connection.tone === "ready" ? connection.detail : config.token ? config.baseUrl : "打开设置页以保存连接信息"}</div>
            </div>
          </div>
        </div>
      </header>

      <main className="container relative z-10 pb-20 pt-8">
        <Outlet />
      </main>
    </div>
  );
}
