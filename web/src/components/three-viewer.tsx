import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

import {
  Viewer3D,
  type ViewerDisplayMode,
  type ViewerModelStats,
  VIEWER_LIGHT_ANGLE_DEFAULT,
  VIEWER_LIGHT_INTENSITY_DEFAULT,
} from "@/lib/viewer";

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
  resetCamera: () => void;
}

export const ThreeViewer = forwardRef<ThreeViewerHandle, {
  url?: string | null;
  message?: string;
  baseUrl?: string;
  token?: string;
  backgroundCenter?: string;
  backgroundEdge?: string;
  className?: string;
  autoRotate?: boolean;
  showGrid?: boolean;
  showShadow?: boolean;
  displayMode?: ViewerDisplayMode;
  lightIntensity?: number;
  lightAngle?: number;
  gridPrimaryColor?: string;
  gridSecondaryColor?: string;
  onModelStatsChange?: (stats: ViewerModelStats | null) => void;
}>(function ThreeViewer({
  url,
  message,
  baseUrl,
  token,
  backgroundCenter = "#2a2a2a",
  backgroundEdge = "#2a2a2a",
  className = "",
  autoRotate = false,
  showGrid = false,
  showShadow = true,
  displayMode = "texture",
  lightIntensity = VIEWER_LIGHT_INTENSITY_DEFAULT,
  lightAngle = VIEWER_LIGHT_ANGLE_DEFAULT,
  gridPrimaryColor,
  gridSecondaryColor,
  onModelStatsChange,
}, ref) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer3D | null>(null);

  useImperativeHandle(ref, () => ({
    resetCamera: () => viewerRef.current?.resetCamera(),
  }), []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const viewer = new Viewer3D(container, {
      backgroundCenter,
      backgroundEdge,
      shadowFloor: showShadow,
      autoRotate,
      showGrid,
      displayMode,
      lightIntensity,
      lightAngle,
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
    viewerRef.current?.setBackground(backgroundCenter, backgroundEdge);
  }, [backgroundCenter, backgroundEdge]);

  useEffect(() => {
    viewerRef.current?.setAutoRotate(autoRotate);
  }, [autoRotate]);

  useEffect(() => {
    viewerRef.current?.setGridVisible(showGrid);
  }, [showGrid]);

  useEffect(() => {
    viewerRef.current?.setShadowVisible(showShadow);
  }, [showShadow]);

  useEffect(() => {
    viewerRef.current?.setDisplayMode(displayMode);
  }, [displayMode]);

  useEffect(() => {
    viewerRef.current?.setLightIntensity(lightIntensity);
  }, [lightIntensity]);

  useEffect(() => {
    viewerRef.current?.setLightAngle(lightAngle);
  }, [lightAngle]);

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
