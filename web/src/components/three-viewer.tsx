import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

import { Viewer3D, type ViewerModelStats } from "@/lib/viewer";

function getArtifactRequestHeaders(url?: string | null, baseUrl?: string, token?: string): Record<string, string> {
  if (!url || !baseUrl || !token) {
    return {};
  }
  try {
    const resource = new URL(url);
    const apiRoot = new URL(baseUrl);
    if (resource.origin !== apiRoot.origin) {
      return {};
    }
    return {
      Authorization: `Bearer ${token}`,
    };
  } catch {
    return {};
  }
}

export interface ThreeViewerHandle {
  zoomIn: () => void;
}

export const ThreeViewer = forwardRef<ThreeViewerHandle, {
  url?: string | null;
  message?: string;
  baseUrl?: string;
  token?: string;
  background?: string;
  className?: string;
  autoRotate?: boolean;
  showGrid?: boolean;
  lightingEnabled?: boolean;
  gridPrimaryColor?: string;
  gridSecondaryColor?: string;
  onModelStatsChange?: (stats: ViewerModelStats | null) => void;
}>(function ThreeViewer({
  url,
  message,
  baseUrl,
  token,
  background = "#2a2a2a",
  className = "",
  autoRotate = false,
  showGrid = false,
  lightingEnabled = true,
  gridPrimaryColor,
  gridSecondaryColor,
  onModelStatsChange,
}, ref) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer3D | null>(null);

  useImperativeHandle(ref, () => ({
    zoomIn: () => viewerRef.current?.zoomBy(0.84),
  }), []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const viewer = new Viewer3D(container, {
      background,
      shadowFloor: true,
      autoRotate,
      showGrid,
      lightingEnabled,
      gridPrimaryColor,
      gridSecondaryColor,
    });
    viewerRef.current = viewer;
    return () => {
      viewer.dispose();
      viewerRef.current = null;
    };
  }, []);

  useEffect(() => {
    viewerRef.current?.setBackground(background);
  }, [background]);

  useEffect(() => {
    viewerRef.current?.setAutoRotate(autoRotate);
  }, [autoRotate]);

  useEffect(() => {
    viewerRef.current?.setGridVisible(showGrid);
  }, [showGrid]);

  useEffect(() => {
    viewerRef.current?.setLightingEnabled(lightingEnabled);
  }, [lightingEnabled]);

  useEffect(() => {
    viewerRef.current?.setGridColors(gridPrimaryColor, gridSecondaryColor);
  }, [gridPrimaryColor, gridSecondaryColor]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) {
      return;
    }
    if (!url) {
      onModelStatsChange?.(null);
      viewer.setMessage(message || "内容准备中");
      return;
    }
    viewer.load(url, getArtifactRequestHeaders(url, baseUrl, token))
      .then((stats) => {
        onModelStatsChange?.(stats ?? null);
      })
      .catch((error) => {
        onModelStatsChange?.(null);
        console.warn("viewer load failed", error);
      });
  }, [baseUrl, message, onModelStatsChange, token, url]);

  return <div ref={containerRef} className={`relative size-full overflow-hidden rounded-[20px] bg-surface-container-lowest ${className}`} />;
});
ThreeViewer.displayName = "ThreeViewer";
