import { Check, CircleDot, Grid3X3, Lightbulb, Orbit, Palette, Pipette, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ThreeViewer, type ThreeViewerHandle } from "@/components/three-viewer";
import { useViewerColors } from "@/hooks/use-viewer-colors";
import {
  type ViewerDisplayMode,
  type ViewerModelStats,
  VIEWER_LIGHT_ANGLE_DEFAULT,
  VIEWER_LIGHT_ANGLE_MAX,
  VIEWER_LIGHT_ANGLE_MIN,
  VIEWER_LIGHT_INTENSITY_DEFAULT,
  VIEWER_LIGHT_INTENSITY_MAX,
  VIEWER_LIGHT_INTENSITY_MIN,
} from "@/lib/viewer";
import { cn } from "@/lib/utils";

const BACKGROUND_PRESETS = [
  {
    id: "deepBlue",
    labelKey: "user.viewer.toolbar.background.presets.deepBlue",
    center: "#1c1e24",
    edge: "#0e0f13",
  },
  {
    id: "slate",
    labelKey: "user.viewer.toolbar.background.presets.slate",
    center: "#2a2e36",
    edge: "#181b21",
  },
  {
    id: "lightGray",
    labelKey: "user.viewer.toolbar.background.presets.lightGray",
    center: "#d7dbe6",
    edge: "#e8ecf2",
  },
  {
    id: "skyDawn",
    labelKey: "user.viewer.toolbar.background.presets.skyDawn",
    center: "#b3bfd4",
    edge: "#c8d0de",
  },
  {
    id: "sunsetGlow",
    labelKey: "user.viewer.toolbar.background.presets.sunsetGlow",
    center: "#baa393",
    edge: "#c4b0a2",
  },
  {
    id: "mistCloud",
    labelKey: "user.viewer.toolbar.background.presets.mistCloud",
    center: "#a3abb8",
    edge: "#b8bfca",
  },
] as const;

const CUSTOM_BACKGROUND_DEFAULT = "#8f97a6";

function darkenHexColor(hexColor: string, ratio = 0.14) {
  const raw = String(hexColor || "").trim();
  const expanded = raw.startsWith("#") ? raw.slice(1) : raw;
  const normalized = expanded.length === 3
    ? expanded.split("").map((char) => `${char}${char}`).join("")
    : expanded;
  if (!/^[\da-fA-F]{6}$/.test(normalized)) {
    return hexColor;
  }
  const clamp = (value: number) => Math.min(255, Math.max(0, Math.round(value)));
  const red = Number.parseInt(normalized.slice(0, 2), 16);
  const green = Number.parseInt(normalized.slice(2, 4), 16);
  const blue = Number.parseInt(normalized.slice(4, 6), 16);
  const factor = Math.min(0.4, Math.max(0.02, ratio));
  const toHex = (value: number) => clamp(value).toString(16).padStart(2, "0");
  return `#${toHex(red * (1 - factor))}${toHex(green * (1 - factor))}${toHex(blue * (1 - factor))}`;
}

type OpenPopover = "light" | "background";

export function ModelViewport({
  url,
  message,
  baseUrl,
  token,
  className,
  topOverlay,
  onModelStatsChange,
}: {
  url?: string | null;
  message?: string;
  baseUrl?: string;
  token?: string;
  className?: string;
  topOverlay?: React.ReactNode;
  onModelStatsChange?: (stats: ViewerModelStats | null) => void;
}) {
  const { t } = useTranslation();
  const viewerColors = useViewerColors();
  const viewerRef = useRef<ThreeViewerHandle | null>(null);
  const toolbarRef = useRef<HTMLDivElement | null>(null);

  const [autoRotate, setAutoRotate] = useState(false);
  const [showGrid, setShowGrid] = useState(false);
  const [showShadow, setShowShadow] = useState(true);
  const [displayMode, setDisplayMode] = useState<ViewerDisplayMode>("texture");
  const [lightIntensity, setLightIntensity] = useState(VIEWER_LIGHT_INTENSITY_DEFAULT);
  const [lightAngle, setLightAngle] = useState(VIEWER_LIGHT_ANGLE_DEFAULT);
  const [openPopover, setOpenPopover] = useState<OpenPopover | null>(null);
  const [manualBackground, setManualBackground] = useState<{
    id: string;
    center: string;
    edge: string;
  } | null>(null);

  useEffect(() => {
    if (!openPopover) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      if (!toolbarRef.current?.contains(event.target as Node)) {
        setOpenPopover(null);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [openPopover]);

  const effectiveBackground = useMemo(() => {
    if (manualBackground) {
      return manualBackground;
    }
    return {
      id: "theme",
      center: viewerColors.backgroundCenter,
      edge: viewerColors.backgroundEdge,
    };
  }, [manualBackground, viewerColors.backgroundCenter, viewerColors.backgroundEdge]);

  const toolbarBtnClass = (active = false) => cn(
    "inline-flex h-10 w-10 items-center justify-center rounded-full border text-sm transition-all duration-200",
    active
      ? "border-[color:color-mix(in_srgb,var(--accent)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_14%,transparent)] text-accent-strong shadow-float"
      : "border-transparent bg-transparent text-text-secondary hover:border-outline hover:bg-surface-container-highest hover:text-text-primary",
  );

  const segmentedModes: { mode: ViewerDisplayMode; label: string }[] = [
    { mode: "texture", label: t("user.viewer.toolbar.displayMode.texture") },
    { mode: "clay", label: t("user.viewer.toolbar.displayMode.clay") },
    { mode: "wireframe", label: t("user.viewer.toolbar.displayMode.wireframe") },
  ];

  return (
    <div className={cn("relative overflow-hidden bg-surface-container-lowest", className)}>
      <div className="absolute inset-0">
        <ThreeViewer
          ref={viewerRef}
          url={url}
          message={message}
          baseUrl={baseUrl}
          token={token}
          backgroundCenter={effectiveBackground.center}
          backgroundEdge={effectiveBackground.edge}
          autoRotate={autoRotate}
          showGrid={showGrid}
          showShadow={showShadow}
          displayMode={displayMode}
          lightIntensity={lightIntensity}
          lightAngle={lightAngle}
          gridPrimaryColor={viewerColors.gridPrimary}
          gridSecondaryColor={viewerColors.gridSecondary}
          onModelStatsChange={onModelStatsChange}
          className="!rounded-none !bg-transparent"
        />
      </div>

      {topOverlay ? (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 p-5">
          {topOverlay}
        </div>
      ) : null}

      <div className="pointer-events-none absolute bottom-6 left-1/2 z-10 -translate-x-1/2">
        <div
          ref={toolbarRef}
          className="pointer-events-auto flex items-center gap-2 rounded-full border border-outline bg-surface-glass px-2 py-1 shadow-float backdrop-blur-xl"
        >
          <div className="flex items-center gap-0.5">
            {segmentedModes.map((item) => (
              <button
                key={item.mode}
                type="button"
                className={cn(
                  "inline-flex h-8 items-center justify-center rounded-full border px-3 text-xs font-medium transition-colors",
                  displayMode === item.mode
                    ? "border-transparent bg-accent text-accent-ink"
                    : "border-transparent text-text-secondary hover:border-outline hover:bg-surface-container-highest hover:text-text-primary",
                )}
                onClick={() => setDisplayMode(item.mode)}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="h-7 w-px bg-outline" />

          <div className="flex items-center gap-0.5">
            <button type="button" className={toolbarBtnClass(autoRotate)} aria-label={t("user.viewer.toolbar.orbit")} title={t("user.viewer.toolbar.orbit")} onClick={() => setAutoRotate((c) => !c)}>
              <Orbit className="h-4 w-4" />
            </button>
            <button type="button" className={toolbarBtnClass(showGrid)} aria-label={t("user.viewer.toolbar.grid")} title={t("user.viewer.toolbar.grid")} onClick={() => setShowGrid((c) => !c)}>
              <Grid3X3 className="h-4 w-4" />
            </button>
            <button type="button" className={toolbarBtnClass(showShadow)} aria-label={t("user.viewer.toolbar.shadow")} title={t("user.viewer.toolbar.shadow")} onClick={() => setShowShadow((c) => !c)}>
              <CircleDot className="h-4 w-4" />
            </button>
            <button type="button" className={toolbarBtnClass(false)} aria-label={t("user.viewer.toolbar.reset")} title={t("user.viewer.toolbar.reset")} onClick={() => viewerRef.current?.resetCamera()}>
              <RotateCcw className="h-4 w-4" />
            </button>
          </div>

          <div className="h-7 w-px bg-outline" />

          <div className="flex items-center gap-0.5">
            <div className="relative">
              <button
                type="button"
                className={toolbarBtnClass(openPopover === "light")}
                aria-label={t("user.viewer.toolbar.light.button")}
                title={t("user.viewer.toolbar.light.button")}
                onClick={() => setOpenPopover((current) => (current === "light" ? null : "light"))}
              >
                <Lightbulb className="h-4 w-4" />
              </button>
              {openPopover === "light" ? (
                <div className="absolute bottom-full right-0 mb-3 w-72 rounded-2xl border border-outline bg-surface-glass p-4 shadow-float backdrop-blur-xl">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-text-muted">
                    {t("user.viewer.toolbar.light.title")}
                  </div>
                  <div className="mt-3 space-y-3">
                    <label className="block">
                      <div className="mb-1.5 flex items-center justify-between text-xs text-text-secondary">
                        <span>{t("user.viewer.toolbar.light.intensity")}</span>
                        <span>{Math.round(lightIntensity * 100)}%</span>
                      </div>
                      <input
                        type="range"
                        min={VIEWER_LIGHT_INTENSITY_MIN}
                        max={VIEWER_LIGHT_INTENSITY_MAX}
                        step={0.01}
                        value={lightIntensity}
                        onChange={(event) => setLightIntensity(Number(event.target.value))}
                        className="viewer-range"
                      />
                    </label>
                    <label className="block">
                      <div className="mb-1.5 flex items-center justify-between text-xs text-text-secondary">
                        <span>{t("user.viewer.toolbar.light.angle")}</span>
                        <span>{Math.round(lightAngle)}°</span>
                      </div>
                      <input
                        type="range"
                        min={VIEWER_LIGHT_ANGLE_MIN}
                        max={VIEWER_LIGHT_ANGLE_MAX}
                        step={1}
                        value={lightAngle}
                        onChange={(event) => setLightAngle(Number(event.target.value))}
                        className="viewer-range"
                      />
                    </label>
                    <button
                      type="button"
                      className="inline-flex h-8 items-center rounded-full border border-outline px-3 text-xs text-text-secondary transition hover:bg-surface-container-high hover:text-text-primary"
                      onClick={() => {
                        setLightIntensity(VIEWER_LIGHT_INTENSITY_DEFAULT);
                        setLightAngle(VIEWER_LIGHT_ANGLE_DEFAULT);
                      }}
                    >
                      {t("user.viewer.toolbar.light.reset")}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="relative">
              <button
                type="button"
                className={toolbarBtnClass(openPopover === "background")}
                aria-label={t("user.viewer.toolbar.background.button")}
                title={t("user.viewer.toolbar.background.button")}
                onClick={() => setOpenPopover((current) => (current === "background" ? null : "background"))}
              >
                <Palette className="h-4 w-4" />
              </button>
              {openPopover === "background" ? (
                <div className="absolute bottom-full right-0 mb-3 w-72 rounded-2xl border border-outline bg-surface-glass p-4 shadow-float backdrop-blur-xl">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-text-muted">
                    {t("user.viewer.toolbar.background.title")}
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      type="button"
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs transition",
                        manualBackground
                          ? "border-outline text-text-secondary hover:bg-surface-container-high hover:text-text-primary"
                          : "border-[color:color-mix(in_srgb,var(--accent)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_12%,transparent)] text-accent-strong",
                      )}
                      onClick={() => setManualBackground(null)}
                    >
                      {!manualBackground ? <Check className="h-3.5 w-3.5" /> : null}
                      {t("user.viewer.toolbar.background.followTheme")}
                    </button>

                    <label
                      className={cn(
                        "relative inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border px-3 text-xs transition",
                        manualBackground?.id === "custom"
                          ? "border-[color:color-mix(in_srgb,var(--accent)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_12%,transparent)] text-accent-strong"
                          : "border-outline text-text-secondary hover:bg-surface-container-high hover:text-text-primary",
                      )}
                      title={t("user.viewer.toolbar.background.custom")}
                      aria-label={t("user.viewer.toolbar.background.custom")}
                    >
                      <input
                        type="color"
                        value={manualBackground?.id === "custom" ? manualBackground.center : CUSTOM_BACKGROUND_DEFAULT}
                        onChange={(event) => {
                          const center = event.target.value;
                          setManualBackground({
                            id: "custom",
                            center,
                            edge: darkenHexColor(center, 0.14),
                          });
                        }}
                        className="absolute inset-0 cursor-pointer opacity-0"
                      />
                      <Pipette className="h-3.5 w-3.5" />
                      <span>{t("user.viewer.toolbar.background.custom")}</span>
                    </label>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {BACKGROUND_PRESETS.map((preset) => {
                      const isActive = manualBackground?.id === preset.id;
                      return (
                        <button
                          key={preset.id}
                          type="button"
                          title={t(preset.labelKey)}
                          aria-label={t(preset.labelKey)}
                          className={cn(
                            "group relative h-8 w-8 rounded-full border transition",
                            isActive
                              ? "border-accent shadow-[0_0_0_2px_color-mix(in_srgb,var(--accent)_24%,transparent)]"
                              : "border-outline hover:border-text-muted",
                          )}
                          onClick={() => setManualBackground(preset)}
                          style={{
                            background: `radial-gradient(circle at 50% 34%, ${preset.center} 0%, ${preset.edge} 90%)`,
                          }}
                        >
                          {isActive ? (
                            <span className="absolute inset-0 grid place-items-center text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.45)]">
                              <Check className="h-3.5 w-3.5" />
                            </span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
