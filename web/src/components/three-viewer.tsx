import { useEffect, useRef } from "react";

import { Viewer3D } from "@/lib/viewer";

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

export function ThreeViewer({
  url,
  message,
  baseUrl,
  token,
  background = "#2a2a2a",
  className = "",
}: {
  url?: string | null;
  message?: string;
  baseUrl?: string;
  token?: string;
  background?: string;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer3D | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const viewer = new Viewer3D(container, {
      background,
      shadowFloor: true,
    });
    viewerRef.current = viewer;
    return () => {
      viewer.dispose();
      viewerRef.current = null;
    };
  }, [background]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) {
      return;
    }
    if (!url) {
      viewer.setMessage(message || "内容准备中");
      return;
    }
    viewer.load(url, getArtifactRequestHeaders(url, baseUrl, token)).catch((error) => {
      console.warn("viewer load failed", error);
    });
  }, [baseUrl, message, token, url]);

  return <div ref={containerRef} className={`relative size-full overflow-hidden rounded-[20px] bg-[#2a2a2a] ${className}`} />;
}
