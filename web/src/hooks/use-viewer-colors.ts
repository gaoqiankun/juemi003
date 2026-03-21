import { useMemo } from "react";

import { useTheme } from "./use-theme";

/**
 * Viewer colors mapped directly from theme state, bypassing CSS variables.
 * This avoids the race condition where getComputedStyle reads stale values
 * because data-theme hasn't been applied to the DOM yet during render.
 */

const COLORS = {
  dark: {
    backgroundCenter: "#222228",
    backgroundEdge: "#111114",
    gridPrimary: "rgba(189, 200, 206, 0.15)",
    gridSecondary: "#6cd3f7",
    textPrimary: "#f5f7fa",
  },
  light: {
    backgroundCenter: "#f4f4f7",
    backgroundEdge: "#e0e0e4",
    gridPrimary: "#e2e2e5",
    gridSecondary: "#00647c",
    textPrimary: "#1a1c1d",
  },
} as const;

export function useViewerColors() {
  const { theme } = useTheme();

  return useMemo(() => COLORS[theme], [theme]);
}
