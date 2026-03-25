export type ViewerDisplayMode = "texture" | "clay" | "wireframe";

export const VIEWER_LIGHT_INTENSITY_DEFAULT = 1;
export const VIEWER_LIGHT_ANGLE_DEFAULT = 28;
export const VIEWER_LIGHT_INTENSITY_MIN = 0;
export const VIEWER_LIGHT_INTENSITY_MAX = 1.5;
export const VIEWER_LIGHT_ANGLE_MIN = 0;
export const VIEWER_LIGHT_ANGLE_MAX = 360;

export interface ViewerModelStats {
  triangleCount: number;
  meshCount: number;
}

export const DEFAULT_BACKGROUND = "#2a2a2a";
export const THUMBNAIL_BACKGROUND = "#2a2a2a";

export const MODEL_CACHE_NAME = "app-model-artifacts-v1";
export const MODEL_ETAG_STORAGE_KEY_PREFIX = "app:model-etag:";

export const ORIGINAL_MATERIAL_KEY = "__viewerOriginalMaterial";
export const OVERRIDE_MATERIAL_KEY = "__viewerOverrideMaterial";
export const WIREFRAME_OVERLAY_KEY = "__viewerWireframeOverlay";
