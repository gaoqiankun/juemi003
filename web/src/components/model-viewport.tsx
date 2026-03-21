import { Grid3X3, Orbit, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ThreeViewer, type ThreeViewerHandle } from "@/components/three-viewer";
import { useViewerColors } from "@/hooks/use-viewer-colors";
import type { ViewerModelStats } from "@/lib/viewer";
import { cn } from "@/lib/utils";

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
  const [autoRotate, setAutoRotate] = useState(true);
  const [showGrid, setShowGrid] = useState(false);

  const toolbarBtnClass = (active = false) => cn(
    "inline-flex h-11 w-11 items-center justify-center rounded-full border text-sm transition-all duration-200",
    active
      ? "border-[color:color-mix(in_srgb,var(--accent)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_14%,transparent)] text-accent-strong shadow-float"
      : "border-transparent bg-transparent text-text-secondary hover:border-outline hover:bg-surface-container-highest hover:text-text-primary",
  );

  return (
    <div className={cn("relative overflow-hidden bg-surface-container-lowest", className)}>
      <div className="absolute inset-0">
        <ThreeViewer
          ref={viewerRef}
          url={url}
          message={message}
          baseUrl={baseUrl}
          token={token}
          backgroundCenter={viewerColors.backgroundCenter}
          backgroundEdge={viewerColors.backgroundEdge}
          autoRotate={autoRotate}
          showGrid={showGrid}
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

      {/* Bottom toolbar */}
      <div className="pointer-events-none absolute bottom-6 left-1/2 z-10 -translate-x-1/2">
        <div className="pointer-events-auto flex items-center gap-1 rounded-full border border-outline bg-surface-glass p-1 shadow-float backdrop-blur-xl">
          <button type="button" className={toolbarBtnClass(autoRotate)} aria-label={t("user.viewer.toolbar.orbit")} title={t("user.viewer.toolbar.orbit")} onClick={() => setAutoRotate((c) => !c)}>
            <Orbit className="h-4 w-4" />
          </button>
          <button type="button" className={toolbarBtnClass(showGrid)} aria-label={t("user.viewer.toolbar.grid")} title={t("user.viewer.toolbar.grid")} onClick={() => setShowGrid((c) => !c)}>
            <Grid3X3 className="h-4 w-4" />
          </button>
          <button type="button" className={toolbarBtnClass(false)} aria-label={t("user.viewer.toolbar.reset")} title={t("user.viewer.toolbar.reset")} onClick={() => viewerRef.current?.resetCamera()}>
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
