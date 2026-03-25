import * as THREE from "three";

export function easeOutCubic(t: number) {
  return 1 - (1 - t) ** 3;
}

export function createRenderer({
  width,
  height,
  alpha = false,
  preserveDrawingBuffer = false,
}: {
  width: number;
  height: number;
  alpha?: boolean;
  preserveDrawingBuffer?: boolean;
}) {
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha,
    preserveDrawingBuffer,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  // ACES filmic tone mapping keeps highlights and PBR materials stable across display modes.
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  return renderer;
}

export function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const precision = value >= 100 || unitIndex === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(precision)} ${units[unitIndex]}`;
}

export function blendColors(c1: string, c2: string, t: number): string {
  const a = new THREE.Color(c1);
  const b = new THREE.Color(c2);
  a.lerp(b, t);
  return `#${a.getHexString()}`;
}

export function createRadialGradientTexture(centerColor: string, edgeColor: string): THREE.CanvasTexture {
  const size = 512;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;

  // Fill base with edge color
  ctx.fillStyle = edgeColor;
  ctx.fillRect(0, 0, size, size);

  // Main light: elliptical glow, shifted slightly above center to simulate top-down studio lighting
  const cx = size * 0.5;
  const cy = size * 0.38;
  const rx = size * 0.6;
  const ry = size * 0.5;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(rx / ry, 1);
  const mainGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, ry);
  mainGrad.addColorStop(0, centerColor);
  mainGrad.addColorStop(0.55, blendColors(centerColor, edgeColor, 0.6));
  mainGrad.addColorStop(1, "transparent");
  ctx.fillStyle = mainGrad;
  ctx.fillRect(-rx, -ry, rx * 2, ry * 2);
  ctx.restore();

  // Subtle secondary fill at bottom to soften the hard edge
  const bottomGrad = ctx.createLinearGradient(0, size * 0.75, 0, size);
  bottomGrad.addColorStop(0, "transparent");
  bottomGrad.addColorStop(1, blendColors(edgeColor, centerColor, 0.08));
  ctx.fillStyle = bottomGrad;
  ctx.fillRect(0, size * 0.75, size, size * 0.25);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}
