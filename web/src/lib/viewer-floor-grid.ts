import * as THREE from "three";

import { getObjectBounds } from "./viewer-object-utils";

export function createShadowFloor() {
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.ShadowMaterial({
      color: 0x000000,
      opacity: 0.18,
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  floor.visible = false;
  return floor;
}

export function createContactShadow() {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(0,0,0,0.22)");
  gradient.addColorStop(0.4, "rgba(0,0,0,0.12)");
  gradient.addColorStop(0.7, "rgba(0,0,0,0.04)");
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  const texture = new THREE.CanvasTexture(canvas);
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.MeshBasicMaterial({
      map: texture,
      transparent: true,
      depthWrite: false,
    }),
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.visible = false;
  return mesh;
}

export function placeContactShadow(shadow: THREE.Mesh, object: THREE.Object3D) {
  const { center, maxDim } = getObjectBounds(object);
  const box = new THREE.Box3().setFromObject(object);
  const spread = maxDim * 1.6;
  shadow.scale.set(spread, spread, 1);
  shadow.position.set(center.x, box.min.y - 0.002, center.z);
  shadow.visible = true;
}

export function placeShadowFloor(floor: THREE.Mesh, object: THREE.Object3D) {
  const { box, center, maxDim } = getObjectBounds(object);
  const floorSize = Math.max(maxDim * 2.6, 4);
  floor.scale.set(floorSize, floorSize, 1);
  floor.position.set(center.x, box.min.y - 0.002, center.z);
  floor.visible = true;
}

interface GridColor {
  r: number;
  g: number;
  b: number;
  a: number;
}

function clampColorChannel(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(255, Math.max(0, value));
}

function clampAlpha(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
}

function parseCssColor(input: string, fallback: GridColor): GridColor {
  const value = String(input || "").trim();
  const rgbaMatch = value.match(/^rgba?\(([^)]+)\)$/i);
  if (rgbaMatch) {
    const parts = rgbaMatch[1].split(",").map((part) => part.trim());
    const parseChannel = (raw: string) => {
      if (raw.endsWith("%")) {
        return clampColorChannel((Number.parseFloat(raw) / 100) * 255);
      }
      return clampColorChannel(Number.parseFloat(raw));
    };
    const parseAlpha = (raw?: string) => {
      if (!raw) {
        return 1;
      }
      if (raw.endsWith("%")) {
        return clampAlpha(Number.parseFloat(raw) / 100);
      }
      return clampAlpha(Number.parseFloat(raw));
    };
    return {
      r: parseChannel(parts[0] || "0"),
      g: parseChannel(parts[1] || "0"),
      b: parseChannel(parts[2] || "0"),
      a: parseAlpha(parts[3]),
    };
  }
  try {
    const color = new THREE.Color(value);
    return {
      r: clampColorChannel(color.r * 255),
      g: clampColorChannel(color.g * 255),
      b: clampColorChannel(color.b * 255),
      a: fallback.a,
    };
  } catch {
    return fallback;
  }
}

function rgbaString(color: GridColor, alphaMultiplier = 1) {
  return `rgba(${Math.round(color.r)}, ${Math.round(color.g)}, ${Math.round(color.b)}, ${clampAlpha(color.a * alphaMultiplier)})`;
}

function createFadingGridTexture(primaryColor: string, secondaryColor: string) {
  const size = 1024;
  const divisions = 40;
  const majorStep = 4;
  const half = size / 2;
  const step = half / divisions;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const primary = parseCssColor(primaryColor, { r: 180, g: 188, b: 196, a: 0.28 });
  const accent = parseCssColor(secondaryColor, { r: 76, g: 203, b: 238, a: 0.52 });

  ctx.clearRect(0, 0, size, size);
  ctx.lineCap = "butt";

  const drawGridLine = (
    x1: number,
    y1: number,
    x2: number,
    y2: number,
    color: GridColor,
    alphaScale: number,
    thickness: number,
  ) => {
    const alpha = color.a * alphaScale;
    if (alpha <= 0.005) {
      return;
    }
    ctx.strokeStyle = rgbaString(color, alphaScale);
    ctx.lineWidth = thickness;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  };

  for (let i = -divisions; i <= divisions; i += 1) {
    const offset = i * step;
    const distanceFactor = Math.abs(i) / divisions;
    const fade = Math.max(0, 1 - distanceFactor ** 1.42);
    if (i === 0) {
      drawGridLine(half + offset, 0, half + offset, size, accent, fade, 1.7);
      drawGridLine(0, half + offset, size, half + offset, accent, fade, 1.7);
      continue;
    }
    const isMajor = i % majorStep === 0;
    const alphaScale = (isMajor ? 0.72 : 0.36) * fade;
    const thickness = isMajor ? 1.1 : 0.8;
    drawGridLine(half + offset, 0, half + offset, size, primary, alphaScale, thickness);
    drawGridLine(0, half + offset, size, half + offset, primary, alphaScale, thickness);
  }

  const edgeFade = ctx.createRadialGradient(half, half, half * 0.24, half, half, half);
  edgeFade.addColorStop(0, "rgba(255,255,255,1)");
  edgeFade.addColorStop(0.66, "rgba(255,255,255,0.9)");
  edgeFade.addColorStop(0.84, "rgba(255,255,255,0.48)");
  edgeFade.addColorStop(1, "rgba(255,255,255,0)");
  ctx.globalCompositeOperation = "destination-in";
  ctx.fillStyle = edgeFade;
  ctx.fillRect(0, 0, size, size);
  ctx.globalCompositeOperation = "source-over";

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}

export function createGridHelper(primaryColor: string, secondaryColor: string) {
  const texture = createFadingGridTexture(primaryColor, secondaryColor);
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
    toneMapped: false,
    side: THREE.DoubleSide,
  });
  const grid = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material);
  grid.rotation.x = -Math.PI / 2;
  grid.visible = false;
  return grid;
}

export function disposeGridHelper(grid: THREE.Mesh) {
  const material = grid.material as THREE.MeshBasicMaterial;
  material.map?.dispose();
  material.dispose();
  grid.geometry.dispose();
}

export function placeGridHelper(grid: THREE.Mesh, object: THREE.Object3D) {
  const { box, center, maxDim } = getObjectBounds(object);
  const gridSize = Math.max(maxDim * 3.4, 4.6);
  grid.scale.set(gridSize, gridSize, 1);
  grid.position.set(center.x, box.min.y + 0.0018, center.z);
  grid.visible = true;
}
