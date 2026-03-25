import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import i18n from "@/i18n";
import { sleep } from "@/lib/utils";

function easeOutCubic(t: number) {
  return 1 - (1 - t) ** 3;
}

function tv(key: string, options?: Record<string, unknown>) {
  return i18n.t(key, options) as string;
}

const DEFAULT_BACKGROUND = "#2a2a2a";
const THUMBNAIL_BACKGROUND = "#2a2a2a";
const MODEL_CACHE_NAME = "app-model-artifacts-v1";
const MODEL_ETAG_STORAGE_KEY_PREFIX = "app:model-etag:";
const loader = new GLTFLoader();

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

function hasFiniteBox(box: THREE.Box3) {
  return Number.isFinite(box.min.x)
    && Number.isFinite(box.min.y)
    && Number.isFinite(box.min.z)
    && Number.isFinite(box.max.x)
    && Number.isFinite(box.max.y)
    && Number.isFinite(box.max.z);
}

function getObjectBounds(object: THREE.Object3D) {
  const box = new THREE.Box3();
  let hasBounds = false;
  object.updateWorldMatrix(true, true);
  object.traverse((child: any) => {
    if (!child.isMesh && !child.isLine && !child.isPoints) {
      return;
    }
    const geometry = child.geometry as THREE.BufferGeometry | undefined;
    if (!geometry) {
      return;
    }
    geometry.computeBoundingBox?.();
    if (!geometry.boundingBox) {
      return;
    }
    const childBox = geometry.boundingBox.clone().applyMatrix4(child.matrixWorld);
    if (!hasFiniteBox(childBox)) {
      return;
    }
    if (!hasBounds) {
      box.copy(childBox);
      hasBounds = true;
      return;
    }
    box.union(childBox);
  });
  if (!hasBounds) {
    box.setFromObject(object);
  }
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  return { box, size, center, maxDim };
}

function normalizeModelRoot(root: THREE.Object3D) {
  const { center, maxDim } = getObjectBounds(root);
  if (!Number.isFinite(maxDim) || maxDim <= 0) {
    throw new Error(tv("user.viewer.runtime.errors.invalidBounds"));
  }
  root.position.sub(center);

  const frame = new THREE.Group();
  frame.add(root);
  frame.scale.setScalar(2 / maxDim);
  frame.updateMatrixWorld(true);
  return frame;
}

function disposeMaterial(material: any) {
  if (!material) {
    return;
  }
  Object.values(material).forEach((value) => {
    if ((value as any)?.isTexture) {
      (value as THREE.Texture).dispose();
    }
  });
  material.dispose?.();
}

function disposeObject(root: THREE.Object3D | null) {
  if (!root) {
    return;
  }
  root.traverse((child: any) => {
    child.geometry?.dispose?.();
    if (Array.isArray(child.material)) {
      child.material.forEach(disposeMaterial);
    } else if (child.material) {
      disposeMaterial(child.material);
    }
  });
}

function disposeMaterialSet(material: THREE.Material | THREE.Material[] | undefined | null) {
  if (!material) {
    return;
  }
  const materials = Array.isArray(material) ? material : [material];
  materials.forEach((entry) => {
    entry.dispose();
  });
}

const ORIGINAL_MATERIAL_KEY = "__viewerOriginalMaterial";
const OVERRIDE_MATERIAL_KEY = "__viewerOverrideMaterial";
const WIREFRAME_OVERLAY_KEY = "__viewerWireframeOverlay";

function createDisplayModeMaterial(baseMaterial: THREE.Material, mode: ViewerDisplayMode) {
  const template = baseMaterial as THREE.MeshStandardMaterial;
  const side = typeof (template as any).side === "number" ? template.side : THREE.FrontSide;
  const isWireframeMode = mode === "wireframe";
  return new THREE.MeshStandardMaterial({
    color: isWireframeMode ? "#d6dae3" : "#c2c3c7",
    roughness: isWireframeMode ? 0.9 : 0.8,
    metalness: 0,
    envMapIntensity: Math.min(Math.max((template.envMapIntensity ?? 1) * (isWireframeMode ? 0.28 : 0.45), 0), 1),
    opacity: 1,
    transparent: false,
    side,
    depthWrite: true,
    flatShading: false,
    polygonOffset: isWireframeMode,
    polygonOffsetFactor: isWireframeMode ? 1 : 0,
    polygonOffsetUnits: isWireframeMode ? 1 : 0,
  });
}

function buildDisplayModeMaterial(
  original: THREE.Material | THREE.Material[],
  mode: ViewerDisplayMode,
): THREE.Material | THREE.Material[] {
  const originals = Array.isArray(original) ? original : [original];
  const next = originals.map((material) => createDisplayModeMaterial(material, mode));
  return Array.isArray(original) ? next : next[0];
}

function disposeWireframeOverlay(overlay: THREE.Object3D | null | undefined) {
  if (!overlay) {
    return;
  }
  overlay.traverse((child: any) => {
    child.geometry?.dispose?.();
    if (Array.isArray(child.material)) {
      child.material.forEach((entry: THREE.Material) => entry.dispose());
    } else if (child.material) {
      child.material.dispose();
    }
  });
}

interface StudioLights {
  rig: THREE.Group;
  key: THREE.DirectionalLight;
  rim: THREE.DirectionalLight;
  fill: THREE.DirectionalLight;
}

const STUDIO_LIGHT_BASE = {
  key: { intensity: 1.15, position: new THREE.Vector3(4.5, 8, 6) },
  rim: { intensity: 0.7, position: new THREE.Vector3(-3, 6, -5) },
  fill: { intensity: 0.35, position: new THREE.Vector3(2, 1, 4) },
} as const;

function applyStudioLightIntensity(lights: StudioLights, gain: number) {
  const normalizedGain = THREE.MathUtils.clamp(gain, VIEWER_LIGHT_INTENSITY_MIN, VIEWER_LIGHT_INTENSITY_MAX);
  lights.key.intensity = STUDIO_LIGHT_BASE.key.intensity * normalizedGain;
  lights.rim.intensity = STUDIO_LIGHT_BASE.rim.intensity * normalizedGain;
  lights.fill.intensity = STUDIO_LIGHT_BASE.fill.intensity * normalizedGain;
}

function applyStudioLightAngle(lights: StudioLights, angleDeg: number) {
  const normalizedAngle = ((angleDeg % 360) + 360) % 360;
  lights.rig.rotation.y = THREE.MathUtils.degToRad(normalizedAngle);
}

function createStudioLights(
  scene: THREE.Scene,
  {
    keyIntensity = 1.15,
    castShadow = true,
  }: {
    keyIntensity?: number;
    castShadow?: boolean;
  } = {},
): StudioLights {
  const rig = new THREE.Group();
  scene.add(rig);

  // Key light — main directional, casts shadow
  const key = new THREE.DirectionalLight(0xfff8f0, keyIntensity);
  key.position.copy(STUDIO_LIGHT_BASE.key.position);
  key.castShadow = castShadow;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.near = 0.5;
  key.shadow.camera.far = 60;
  key.shadow.radius = 3.5;
  key.shadow.bias = -0.00015;
  rig.add(key);

  // Rim light — behind and above, silhouette highlight
  const rim = new THREE.DirectionalLight(0xc8deff, 0.7);
  rim.position.copy(STUDIO_LIGHT_BASE.rim.position);
  rig.add(rim);

  // Fill light — front-low, softens shadows
  const fill = new THREE.DirectionalLight(0xe8f0ff, 0.35);
  fill.position.copy(STUDIO_LIGHT_BASE.fill.position);
  rig.add(fill);

  const lights = { rig, key, rim, fill };
  applyStudioLightAngle(lights, VIEWER_LIGHT_ANGLE_DEFAULT);
  const initialGain = keyIntensity / STUDIO_LIGHT_BASE.key.intensity;
  applyStudioLightIntensity(lights, VIEWER_LIGHT_INTENSITY_DEFAULT * initialGain);
  return lights;
}

function createEnvironmentMap(scene: THREE.Scene, renderer: THREE.WebGLRenderer) {
  const pmremGenerator = new THREE.PMREMGenerator(renderer);
  pmremGenerator.compileCubemapShader();

  const roomEnvironment = new RoomEnvironment();
  // Studio-tuned panel colors: neutral whites with subtle warm/cool accents
  // for clean reflections on metallic and glossy materials
  const panelColors = [
    { color: "#e0eaff", intensity: 55 },  // cool top
    { color: "#d8e8ff", intensity: 50 },  // cool side
    { color: "#fff4e6", intensity: 28 },  // warm accent
    { color: "#c8d8f0", intensity: 40 },  // neutral
    { color: "#ffe8d8", intensity: 20 },  // warm accent
    { color: "#f0f0f0", intensity: 90 },  // ground bounce
  ];
  let panelIndex = 0;

  roomEnvironment.traverse((object: THREE.Object3D) => {
    if (!(object as THREE.Mesh).isMesh) {
      return;
    }
    const material = (object as THREE.Mesh).material;
    if (!(material instanceof THREE.MeshBasicMaterial)) {
      return;
    }
    const preset = panelColors[Math.min(panelIndex, panelColors.length - 1)];
    material.color.set(preset.color).multiplyScalar(preset.intensity);
    panelIndex += 1;
  });

  const envMap = pmremGenerator.fromScene(roomEnvironment, 0.04).texture;
  scene.environment = envMap;

  return {
    texture: envMap,
    dispose: () => {
      scene.environment = null;
      envMap.dispose();
      roomEnvironment.dispose();
      pmremGenerator.dispose();
    },
  };
}

function createShadowFloor() {
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

function createContactShadow() {
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

function placeContactShadow(shadow: THREE.Mesh, object: THREE.Object3D) {
  const { center, maxDim } = getObjectBounds(object);
  const box = new THREE.Box3().setFromObject(object);
  const spread = maxDim * 1.6;
  shadow.scale.set(spread, spread, 1);
  shadow.position.set(center.x, box.min.y - 0.002, center.z);
  shadow.visible = true;
}

function placeShadowFloor(floor: THREE.Mesh, object: THREE.Object3D) {
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

function createGridHelper(primaryColor: string, secondaryColor: string) {
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

function disposeGridHelper(grid: THREE.Mesh) {
  const material = grid.material as THREE.MeshBasicMaterial;
  material.map?.dispose();
  material.dispose();
  grid.geometry.dispose();
}

function placeGridHelper(grid: THREE.Mesh, object: THREE.Object3D) {
  const { box, center, maxDim } = getObjectBounds(object);
  const gridSize = Math.max(maxDim * 3.4, 4.6);
  grid.scale.set(gridSize, gridSize, 1);
  grid.position.set(center.x, box.min.y + 0.0018, center.z);
  grid.visible = true;
}

function getModelStats(object: THREE.Object3D): ViewerModelStats {
  let triangleCount = 0;
  let meshCount = 0;

  object.traverse((child: any) => {
    if (!child.isMesh) {
      return;
    }
    const geometry = child.geometry as THREE.BufferGeometry | undefined;
    if (!geometry) {
      return;
    }
    meshCount += 1;
    const position = geometry.getAttribute("position");
    if (!position) {
      return;
    }
    triangleCount += geometry.index
      ? geometry.index.count / 3
      : position.count / 3;
  });

  return {
    triangleCount: Math.round(triangleCount),
    meshCount,
  };
}

function fitCameraToObject(
  camera: THREE.PerspectiveCamera,
  object: THREE.Object3D,
  controls: OrbitControls | null,
  aspect = 1,
) {
  const { center, maxDim } = getObjectBounds(object);
  const fov = THREE.MathUtils.degToRad(camera.fov);
  const distance = Math.max(
    (maxDim * 0.85) / Math.tan(fov / 2),
    (maxDim * 0.6) / Math.tan((fov * aspect) / 2),
  ) * 1.35;
  const offset = new THREE.Vector3(1, 0.75, 1).normalize().multiplyScalar(distance);

  camera.position.copy(center).add(offset);
  camera.near = Math.max(distance / 100, 0.01);
  camera.far = distance * 100;
  camera.updateProjectionMatrix();

  if (controls) {
    controls.target.copy(center);
    controls.update();
  } else {
    camera.lookAt(center);
  }
}

function createRenderer({
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

function canUseModelCache() {
  return typeof window !== "undefined" && "caches" in window;
}

function rememberModelEtag(url: string, etag: string | null) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    const storageKey = `${MODEL_ETAG_STORAGE_KEY_PREFIX}${url}`;
    if (etag) {
      window.localStorage.setItem(storageKey, etag);
      return;
    }
    window.localStorage.removeItem(storageKey);
  } catch {
    // Ignore cache metadata failures and continue with network data.
  }
}

async function readCachedModelBlob(url: string, onStatus?: (message: string) => void) {
  if (!canUseModelCache()) {
    return null;
  }
  try {
    const cache = await window.caches.open(MODEL_CACHE_NAME);
    const cachedResponse = await cache.match(url);
    if (!cachedResponse) {
      return null;
    }
    onStatus?.(tv("user.viewer.runtime.status.readingCache"));
    const blob = await cachedResponse.blob();
    onStatus?.(tv("user.viewer.runtime.status.cacheReady"));
    return blob;
  } catch {
    return null;
  }
}

async function cacheModelBlob(
  url: string,
  blob: Blob,
  contentType: string,
  etag: string | null,
) {
  rememberModelEtag(url, etag);
  if (!canUseModelCache()) {
    return;
  }
  try {
    const headers = new Headers({
      "content-length": String(blob.size),
      "content-type": contentType,
    });
    if (etag) {
      headers.set("etag", etag);
    }
    const cache = await window.caches.open(MODEL_CACHE_NAME);
    await cache.put(url, new Response(blob, { headers }));
  } catch {
    // Ignore disk cache failures and keep the in-memory render path working.
  }
}

async function readModelBlob(
  response: Response,
  onStatus?: (message: string) => void,
) {
  const contentType = response.headers.get("content-type") || "model/gltf-binary";
  const totalBytes = Number(response.headers.get("content-length") || 0);

  if (!response.body || typeof response.body.getReader !== "function") {
    onStatus?.(
      totalBytes > 0
        ? tv("user.viewer.runtime.status.receivingWithSize", { size: formatBytes(totalBytes) })
        : tv("user.viewer.runtime.status.receiving"),
    );
    return response.blob();
  }

  const reader = response.body.getReader();
  const chunks: ArrayBuffer[] = [];
  let receivedBytes = 0;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      if (!value) {
        continue;
      }

      const chunk = new Uint8Array(value.byteLength);
      chunk.set(value);
      chunks.push(chunk.buffer);
      receivedBytes += value.byteLength;

      if (totalBytes > 0) {
        const percent = Math.min(99, Math.round((receivedBytes / totalBytes) * 100));
        onStatus?.(tv("user.viewer.runtime.status.downloadingPercent", { percent }));
      } else {
        onStatus?.(tv("user.viewer.runtime.status.receivingWithSize", { size: formatBytes(receivedBytes) }));
      }
    }
  } finally {
    reader.releaseLock();
  }

  onStatus?.(tv("user.viewer.runtime.status.receivedAndParsing"));
  return new Blob(chunks, { type: contentType });
}

async function fetchModelBlobUrl(
  url: string,
  requestHeaders: Record<string, string> = {},
  onStatus?: (message: string) => void,
) {
  const cachedBlob = await readCachedModelBlob(url, onStatus);
  if (cachedBlob) {
    return URL.createObjectURL(cachedBlob);
  }

  const response = await fetch(url, {
    headers: requestHeaders,
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(tv("user.viewer.runtime.errors.requestFailed", {
      status: response.status,
      statusText: response.statusText,
    }));
  }
  const totalBytes = Number(response.headers.get("content-length") || 0);
  onStatus?.(
    totalBytes > 0
      ? tv("user.viewer.runtime.status.downloadingStart", { size: formatBytes(totalBytes) })
      : tv("user.viewer.runtime.status.receiving"),
  );
  const blob = await readModelBlob(response, onStatus);
  const contentType = response.headers.get("content-type") || "model/gltf-binary";
  void cacheModelBlob(url, blob, contentType, response.headers.get("etag"));
  return URL.createObjectURL(blob);
}

async function loadScene(
  url: string,
  requestHeaders: Record<string, string> = {},
  onStatus?: (message: string) => void,
) {
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    let objectUrl = "";
    try {
      onStatus?.(
        attempt === 1
          ? tv("user.viewer.runtime.status.requesting")
          : tv("user.viewer.runtime.status.retrying", { attempt }),
      );
      objectUrl = await fetchModelBlobUrl(url, requestHeaders, onStatus);
      onStatus?.(tv("user.viewer.runtime.status.parsingStructure"));
      const gltf = await loader.loadAsync(objectUrl);
      const root = gltf.scene || gltf.scenes?.[0];
      if (!root) {
        throw new Error(tv("user.viewer.runtime.errors.incompleteFile"));
      }
      onStatus?.(tv("user.viewer.runtime.status.preparingView"));
      root.traverse((child: any) => {
        if (child.isMesh && child.material) {
          child.castShadow = true;
          child.receiveShadow = true;
          const materials = Array.isArray(child.material) ? child.material : [child.material];
          materials.forEach((material: any) => {
            material.side = THREE.FrontSide;
            if (typeof material.envMapIntensity === "number") {
              material.envMapIntensity = Math.max(material.envMapIntensity, 1.4);
            }
            if (material.isMeshStandardMaterial || material.isMeshPhysicalMaterial) {
              if (typeof material.roughness === "number") {
                material.roughness = Math.min(material.roughness, 0.65);
              }
              if (typeof material.metalness === "number") {
                material.metalness = Math.max(material.metalness, 0.08);
              }
            }
            material.needsUpdate = true;
          });
        }
      });
      return normalizeModelRoot(root);
    } catch (error) {
      lastError = error;
      if (attempt === 3) {
        throw error;
      }
      await sleep(450 * attempt);
    } finally {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    }
  }
  throw lastError || new Error(tv("user.viewer.runtime.errors.loadFailed"));
}

function formatViewerErrorMessage(error: unknown) {
  if (error instanceof Error) {
    const detail = error.message.trim();
    if (!detail) {
      return tv("user.viewer.runtime.errors.previewFailed");
    }
    return detail;
  }
  return tv("user.viewer.runtime.errors.previewFailed");
}

function createRadialGradientTexture(centerColor: string, edgeColor: string): THREE.CanvasTexture {
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

function blendColors(c1: string, c2: string, t: number): string {
  const a = new THREE.Color(c1);
  const b = new THREE.Color(c2);
  a.lerp(b, t);
  return `#${a.getHexString()}`;
}

export class Viewer3D {
  container: HTMLElement;
  options: {
    backgroundCenter: string;
    backgroundEdge: string;
    displayMode: ViewerDisplayMode;
    autoRotate: boolean;
    shadowFloor: boolean;
    showGrid: boolean;
    lightingEnabled: boolean;
    lightIntensity: number;
    lightAngle: number;
    gridPrimaryColor: string;
    gridSecondaryColor: string;
  };
  backgroundTexture: THREE.CanvasTexture | null;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  modelRoot: THREE.Object3D | null;
  shadowFloor: THREE.Mesh | null;
  contactShadow: THREE.Mesh;
  gridHelper: THREE.Mesh;
  studioLights: StudioLights;
  environmentTexture: THREE.Texture | null;
  disposeEnvironment: (() => void) | null;
  displayMode: ViewerDisplayMode;
  gridVisible: boolean;
  shadowVisible: boolean;
  lightingEnabled: boolean;
  lightIntensity: number;
  lightAngle: number;
  frameHandle = 0;
  loadToken = 0;
  flyInProgress = 0;
  flyInFrom: THREE.Vector3 | null = null;
  flyInTo: THREE.Vector3 | null = null;
  defaultCameraPosition: THREE.Vector3;
  defaultCameraTarget: THREE.Vector3;
  cameraReset: {
    fromPosition: THREE.Vector3;
    toPosition: THREE.Vector3;
    fromTarget: THREE.Vector3;
    toTarget: THREE.Vector3;
    startTime: number;
    durationMs: number;
  } | null = null;
  fadeInProgress = 0;
  fadeInMaterials: THREE.Material[] = [];
  overlay: HTMLDivElement;
  resizeObserver: ResizeObserver;

  constructor(
    container: HTMLElement,
    options: {
      backgroundCenter?: string;
      backgroundEdge?: string;
      displayMode?: ViewerDisplayMode;
      autoRotate?: boolean;
      shadowFloor?: boolean;
      showGrid?: boolean;
      lightingEnabled?: boolean;
      lightIntensity?: number;
      lightAngle?: number;
      gridPrimaryColor?: string;
      gridSecondaryColor?: string;
    } = {},
  ) {
    this.container = container;
    this.options = {
      backgroundCenter: options.backgroundCenter || DEFAULT_BACKGROUND,
      backgroundEdge: options.backgroundEdge || DEFAULT_BACKGROUND,
      displayMode: options.displayMode || "texture",
      autoRotate: Boolean(options.autoRotate),
      shadowFloor: options.shadowFloor !== false,
      showGrid: Boolean(options.showGrid),
      lightingEnabled: options.lightingEnabled !== false,
      lightIntensity: THREE.MathUtils.clamp(
        options.lightIntensity ?? VIEWER_LIGHT_INTENSITY_DEFAULT,
        VIEWER_LIGHT_INTENSITY_MIN,
        VIEWER_LIGHT_INTENSITY_MAX,
      ),
      lightAngle: THREE.MathUtils.clamp(
        options.lightAngle ?? VIEWER_LIGHT_ANGLE_DEFAULT,
        VIEWER_LIGHT_ANGLE_MIN,
        VIEWER_LIGHT_ANGLE_MAX,
      ),
      gridPrimaryColor: options.gridPrimaryColor || "rgba(189, 200, 206, 0.3)",
      gridSecondaryColor: options.gridSecondaryColor || "rgba(8, 145, 178, 0.2)",
    };
    this.backgroundTexture = null;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1000);
    this.renderer = createRenderer({
      width: Math.max(this.container.clientWidth, 1),
      height: Math.max(this.container.clientHeight, 1),
    });
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.minDistance = 0.4;
    this.controls.maxDistance = 80;
    this.controls.autoRotate = this.options.autoRotate;
    this.controls.autoRotateSpeed = 1.25;
    this.modelRoot = null;
    this.shadowFloor = createShadowFloor();
    this.gridHelper = createGridHelper(this.options.gridPrimaryColor, this.options.gridSecondaryColor);
    this.studioLights = {
      rig: new THREE.Group(),
      key: new THREE.DirectionalLight(),
      rim: new THREE.DirectionalLight(),
      fill: new THREE.DirectionalLight(),
    };
    this.contactShadow = createContactShadow();
    this.environmentTexture = null;
    this.disposeEnvironment = null;
    this.displayMode = this.options.displayMode;
    this.gridVisible = this.options.showGrid;
    this.shadowVisible = this.options.shadowFloor;
    this.lightingEnabled = this.options.lightingEnabled;
    this.lightIntensity = this.options.lightIntensity;
    this.lightAngle = this.options.lightAngle;

    this.container.innerHTML = "";
    this.renderer.domElement.className = "size-full";
    this.container.appendChild(this.renderer.domElement);

    this.overlay = document.createElement("div");
    this.overlay.className = "absolute inset-0 flex items-center justify-center bg-[color:color-mix(in_srgb,var(--surface-container-lowest)_74%,transparent)] backdrop-blur-[1px]";
    this.overlay.style.display = "none";
    this.container.appendChild(this.overlay);

    this.backgroundTexture = createRadialGradientTexture(this.options.backgroundCenter, this.options.backgroundEdge);
    this.scene.background = this.backgroundTexture;
    this.studioLights = createStudioLights(this.scene);
    const environment = createEnvironmentMap(this.scene, this.renderer);
    this.environmentTexture = environment.texture;
    this.disposeEnvironment = environment.dispose;
    this.scene.add(this.shadowFloor);
    this.scene.add(this.contactShadow);
    this.scene.add(this.gridHelper);
    this.setLightingEnabled(this.lightingEnabled);
    this.setLightIntensity(this.lightIntensity);
    this.setLightAngle(this.lightAngle);
    this.setGridVisible(this.gridVisible);
    this.setShadowVisible(this.shadowVisible);
    this.camera.position.set(2.5, 1.8, 2.5);
    this.controls.update();
    this.defaultCameraPosition = this.camera.position.clone();
    this.defaultCameraTarget = this.controls.target.clone();

    this.handleResize = this.handleResize.bind(this);
    this.animate = this.animate.bind(this);
    this.resizeObserver = new ResizeObserver(this.handleResize);
    this.resizeObserver.observe(this.container);
    this.handleResize();
    this.animate();
  }

  private handleResize() {
    const width = Math.max(this.container.clientWidth, 1);
    const height = Math.max(this.container.clientHeight, 1);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  private animate() {
    this.frameHandle = window.requestAnimationFrame(this.animate);
    const now = performance.now();

    // Camera fly-in animation
    if (this.flyInFrom && this.flyInTo && this.flyInProgress < 1) {
      this.flyInProgress = Math.min(this.flyInProgress + 0.018, 1);
      const t = easeOutCubic(this.flyInProgress);
      this.camera.position.lerpVectors(this.flyInFrom, this.flyInTo, t);
    }

    // Camera reset animation to smoothly return to the default model framing
    if (this.cameraReset) {
      const elapsed = Math.max(0, now - this.cameraReset.startTime);
      const progress = Math.min(1, elapsed / this.cameraReset.durationMs);
      const eased = progress < 0.5
        ? 4 * progress ** 3
        : 1 - ((-2 * progress + 2) ** 3) / 2;
      this.camera.position.lerpVectors(this.cameraReset.fromPosition, this.cameraReset.toPosition, eased);
      this.controls.target.lerpVectors(this.cameraReset.fromTarget, this.cameraReset.toTarget, eased);
      if (progress >= 1) {
        this.cameraReset = null;
      }
    }

    // Model fade-in animation
    if (this.fadeInProgress < 1 && this.fadeInMaterials.length > 0) {
      this.fadeInProgress = Math.min(this.fadeInProgress + 0.025, 1);
      const opacity = easeOutCubic(this.fadeInProgress);
      for (const material of this.fadeInMaterials) {
        (material as any).opacity = opacity;
        if (this.fadeInProgress >= 1) {
          // Restore original transparency state for non-transparent materials
          if (!(material as any)._wasTransparent) {
            material.transparent = false;
          }
        }
      }
    }

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  setMessage(message: string, tone: "info" | "loading" | "error" = "info") {
    const toneClass = tone === "error"
      ? "border-[color:color-mix(in_srgb,var(--danger)_28%,transparent)] bg-surface-glass text-text-primary"
      : tone === "loading"
        ? "border-outline bg-surface-glass text-text-primary"
        : "border-outline bg-surface-glass text-text-secondary";
    this.overlay.hidden = false;
    this.overlay.style.display = "flex";
    this.overlay.innerHTML = `<div class="rounded-full border px-4 py-2 text-sm ${toneClass}">${message}</div>`;
  }

  setBackground(centerColor: string, edgeColor: string) {
    if (centerColor === this.options.backgroundCenter && edgeColor === this.options.backgroundEdge) {
      return;
    }
    this.options.backgroundCenter = centerColor;
    this.options.backgroundEdge = edgeColor;
    if (this.backgroundTexture) {
      this.backgroundTexture.dispose();
    }
    this.backgroundTexture = createRadialGradientTexture(centerColor, edgeColor);
    this.scene.background = this.backgroundTexture;
  }

  setGridColors(primaryColor?: string, secondaryColor?: string) {
    const nextPrimaryColor = primaryColor || this.options.gridPrimaryColor;
    const nextSecondaryColor = secondaryColor || this.options.gridSecondaryColor;
    if (
      nextPrimaryColor === this.options.gridPrimaryColor
      && nextSecondaryColor === this.options.gridSecondaryColor
    ) {
      return;
    }

    this.options.gridPrimaryColor = nextPrimaryColor;
    this.options.gridSecondaryColor = nextSecondaryColor;

    const previousGrid = this.gridHelper;
    this.scene.remove(previousGrid);
    disposeGridHelper(previousGrid);

    this.gridHelper = createGridHelper(nextPrimaryColor, nextSecondaryColor);
    this.scene.add(this.gridHelper);
    this.setGridVisible(this.gridVisible);
  }

  setAutoRotate(enabled: boolean) {
    this.controls.autoRotate = enabled;
    this.controls.update();
  }

  setGridVisible(enabled: boolean) {
    this.gridVisible = enabled;
    if (!enabled || !this.modelRoot) {
      this.gridHelper.visible = false;
      return;
    }
    placeGridHelper(this.gridHelper, this.modelRoot);
  }

  setShadowVisible(visible: boolean) {
    this.shadowVisible = visible;
    this.options.shadowFloor = visible;
    const canShowShadow = visible && this.lightingEnabled && Boolean(this.modelRoot);
    if (!canShowShadow || !this.modelRoot) {
      if (this.shadowFloor) {
        this.shadowFloor.visible = false;
      }
      this.contactShadow.visible = false;
      return;
    }
    if (this.shadowFloor) {
      this.shadowFloor.visible = true;
      placeShadowFloor(this.shadowFloor, this.modelRoot);
    }
    this.contactShadow.visible = true;
    placeContactShadow(this.contactShadow, this.modelRoot);
  }

  private addWireframeOverlay(mesh: THREE.Mesh) {
    const current = mesh.userData[WIREFRAME_OVERLAY_KEY] as THREE.Object3D | undefined;
    if (current) {
      return;
    }
    const geometry = mesh.geometry as THREE.BufferGeometry | undefined;
    if (!geometry) {
      return;
    }
    const wireframeGeometry = new THREE.WireframeGeometry(geometry);
    const wireframeMaterial = new THREE.LineBasicMaterial({
      color: "#2a2d35",
      transparent: true,
      opacity: 1,
      depthWrite: false,
      toneMapped: false,
    });
    const lines = new THREE.LineSegments(wireframeGeometry, wireframeMaterial);
    lines.renderOrder = 8;
    mesh.add(lines);
    mesh.userData[WIREFRAME_OVERLAY_KEY] = lines;
  }

  private removeWireframeOverlay(mesh: THREE.Mesh) {
    const overlay = mesh.userData[WIREFRAME_OVERLAY_KEY] as THREE.Object3D | undefined;
    if (!overlay) {
      return;
    }
    mesh.remove(overlay);
    disposeWireframeOverlay(overlay);
    delete mesh.userData[WIREFRAME_OVERLAY_KEY];
  }

  private restoreOriginalMaterials(root: THREE.Object3D, disposeOverrides = true) {
    root.traverse((child: any) => {
      if (!child.isMesh) {
        return;
      }
      const mesh = child as THREE.Mesh;
      this.removeWireframeOverlay(mesh);
      const original = mesh.userData[ORIGINAL_MATERIAL_KEY] as THREE.Material | THREE.Material[] | undefined;
      const override = mesh.userData[OVERRIDE_MATERIAL_KEY] as THREE.Material | THREE.Material[] | undefined;

      if (original) {
        mesh.material = original;
      }
      if (override && disposeOverrides) {
        disposeMaterialSet(override);
      }

      delete mesh.userData[ORIGINAL_MATERIAL_KEY];
      delete mesh.userData[OVERRIDE_MATERIAL_KEY];
    });
  }

  private applyDisplayModeToModel() {
    if (!this.modelRoot) {
      return;
    }
    this.modelRoot.traverse((child: any) => {
      if (!child.isMesh || !child.material) {
        return;
      }
      const mesh = child as THREE.Mesh;
      const original = (mesh.userData[ORIGINAL_MATERIAL_KEY] as THREE.Material | THREE.Material[] | undefined)
        || (mesh.material as THREE.Material | THREE.Material[]);
      mesh.userData[ORIGINAL_MATERIAL_KEY] = original;
      this.removeWireframeOverlay(mesh);

      const previousOverride = mesh.userData[OVERRIDE_MATERIAL_KEY] as THREE.Material | THREE.Material[] | undefined;
      if (this.displayMode === "texture") {
        mesh.material = original;
        if (previousOverride) {
          disposeMaterialSet(previousOverride);
        }
        delete mesh.userData[OVERRIDE_MATERIAL_KEY];
        return;
      }

      const nextOverride = buildDisplayModeMaterial(original, this.displayMode);
      mesh.material = nextOverride;
      if (previousOverride) {
        disposeMaterialSet(previousOverride);
      }
      mesh.userData[OVERRIDE_MATERIAL_KEY] = nextOverride;
      if (this.displayMode === "wireframe") {
        this.addWireframeOverlay(mesh);
      }
    });
  }

  setDisplayMode(mode: ViewerDisplayMode) {
    const normalizedMode = (mode || "texture") as ViewerDisplayMode;
    this.displayMode = normalizedMode;
    this.options.displayMode = normalizedMode;
    this.applyDisplayModeToModel();
    this.setLightIntensity(this.lightIntensity);
  }

  setLightIntensity(factor: number) {
    const normalizedFactor = THREE.MathUtils.clamp(factor, VIEWER_LIGHT_INTENSITY_MIN, VIEWER_LIGHT_INTENSITY_MAX);
    this.lightIntensity = normalizedFactor;
    this.options.lightIntensity = normalizedFactor;
    const effectiveFactor = this.displayMode === "clay" ? normalizedFactor * 0.5 : normalizedFactor;
    applyStudioLightIntensity(this.studioLights, effectiveFactor);
  }

  setLightAngle(degrees: number) {
    const normalizedAngle = ((degrees % 360) + 360) % 360;
    this.lightAngle = normalizedAngle;
    this.options.lightAngle = normalizedAngle;
    applyStudioLightAngle(this.studioLights, normalizedAngle);
  }

  setLightingEnabled(enabled: boolean) {
    this.lightingEnabled = enabled;
    this.studioLights.rig.visible = enabled;
    this.scene.environment = enabled ? this.environmentTexture : null;
    this.renderer.toneMappingExposure = enabled ? 1.0 : 0.86;
    if (enabled) {
      this.setLightIntensity(this.lightIntensity);
      this.setLightAngle(this.lightAngle);
    }
    this.setShadowVisible(this.shadowVisible);
  }

  resetCamera(durationMs = 520) {
    this.flyInFrom = null;
    this.flyInTo = null;
    this.flyInProgress = 1;

    const toPosition = this.defaultCameraPosition.clone();
    const toTarget = this.defaultCameraTarget.clone();
    if (
      this.camera.position.distanceToSquared(toPosition) < 1e-6
      && this.controls.target.distanceToSquared(toTarget) < 1e-6
    ) {
      return;
    }

    this.cameraReset = {
      fromPosition: this.camera.position.clone(),
      toPosition,
      fromTarget: this.controls.target.clone(),
      toTarget,
      startTime: performance.now(),
      durationMs: Math.max(220, durationMs),
    };
  }

  zoomBy(factor: number) {
    const direction = this.camera.position.clone().sub(this.controls.target);
    const nextDistance = THREE.MathUtils.clamp(
      direction.length() * factor,
      this.controls.minDistance,
      this.controls.maxDistance,
    );
    direction.setLength(nextDistance);
    this.camera.position.copy(this.controls.target).add(direction);
    this.controls.update();
  }

  clearModel() {
    this.cameraReset = null;
    this.fadeInMaterials = [];
    if (!this.modelRoot) {
      this.gridHelper.visible = false;
      if (this.shadowFloor) {
        this.shadowFloor.visible = false;
      }
      this.contactShadow.visible = false;
      return;
    }
    this.restoreOriginalMaterials(this.modelRoot, true);
    this.scene.remove(this.modelRoot);
    disposeObject(this.modelRoot);
    this.modelRoot = null;
    this.gridHelper.visible = false;
    if (this.shadowFloor) {
      this.shadowFloor.visible = false;
    }
    this.contactShadow.visible = false;
  }

  async load(url?: string | null, requestHeaders: Record<string, string> = {}) {
    if (!url) {
      this.clearModel();
      if (this.shadowFloor) {
        this.shadowFloor.visible = false;
      }
      this.gridHelper.visible = false;
      this.setMessage(tv("user.viewer.runtime.status.notReady"));
      return null;
    }

    const currentToken = ++this.loadToken;
    this.setMessage(tv("user.viewer.runtime.status.requesting"), "loading");
    let root: THREE.Object3D | null = null;
    try {
      root = await loadScene(url, requestHeaders, (nextMessage) => {
        if (currentToken !== this.loadToken) {
          return;
        }
        this.setMessage(nextMessage, "loading");
      });
      if (currentToken !== this.loadToken) {
        disposeObject(root);
        return;
      }
      this.clearModel();
      this.modelRoot = root;
      this.applyDisplayModeToModel();

      // Prepare fade-in: set all materials transparent at opacity 0
      this.fadeInMaterials = [];
      this.fadeInProgress = 0;
      root.traverse((child: any) => {
        if (!child.isMesh || !child.material) {
          return;
        }
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        for (const mat of materials) {
          (mat as any)._wasTransparent = mat.transparent;
          mat.transparent = true;
          mat.opacity = 0;
          this.fadeInMaterials.push(mat);
        }
      });

      this.scene.add(root);
      this.setShadowVisible(this.shadowVisible);
      if (this.gridVisible) {
        placeGridHelper(this.gridHelper, root);
      }

      // Compute final camera position, then set up fly-in from further back
      const aspect = Math.max(this.container.clientWidth, 1) / Math.max(this.container.clientHeight, 1);
      fitCameraToObject(this.camera, root, this.controls, aspect);
      this.defaultCameraPosition.copy(this.camera.position);
      this.defaultCameraTarget.copy(this.controls.target);
      const targetPos = this.defaultCameraPosition.clone();
      const direction = targetPos.clone().sub(this.defaultCameraTarget).normalize();
      const startPos = targetPos.clone().add(direction.multiplyScalar(1.8));
      this.camera.position.copy(startPos);
      this.flyInFrom = startPos;
      this.flyInTo = targetPos;
      this.flyInProgress = 0;

      this.overlay.hidden = true;
      this.overlay.style.display = "none";
      return getModelStats(root);
    } catch (error) {
      if (root) {
        disposeObject(root);
      }
      this.clearModel();
      if (this.shadowFloor) {
        this.shadowFloor.visible = false;
      }
      this.gridHelper.visible = false;
      this.setMessage(formatViewerErrorMessage(error), "error");
      throw error;
    }
  }

  dispose() {
    this.loadToken += 1;
    if (this.frameHandle) {
      window.cancelAnimationFrame(this.frameHandle);
    }
    this.resizeObserver.disconnect();
    this.controls.dispose();
    this.clearModel();
    this.disposeEnvironment?.();
    this.disposeEnvironment = null;
    this.environmentTexture = null;
    this.scene.remove(this.gridHelper);
    disposeGridHelper(this.gridHelper);
    if (this.shadowFloor) {
      this.scene.remove(this.shadowFloor);
      (this.shadowFloor.material as THREE.ShadowMaterial).dispose();
      this.shadowFloor.geometry.dispose();
      this.shadowFloor = null;
    }
    this.scene.remove(this.contactShadow);
    (this.contactShadow.material as THREE.MeshBasicMaterial).map?.dispose();
    this.contactShadow.geometry.dispose();
    (this.contactShadow.material as THREE.MeshBasicMaterial).dispose();
    this.backgroundTexture?.dispose();
    this.backgroundTexture = null;
    this.renderer.dispose();
    this.container.innerHTML = "";
  }
}

export async function renderModelThumbnail(
  url: string,
  {
    width = 400,
    height = 400,
    background = THUMBNAIL_BACKGROUND,
    requestHeaders = {},
  }: {
    width?: number;
    height?: number;
    background?: string;
    requestHeaders?: Record<string, string>;
  } = {},
) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(background);
  const camera = new THREE.PerspectiveCamera(34, width / height, 0.1, 1000);
  const renderer = createRenderer({
    width,
    height,
    preserveDrawingBuffer: true,
  });
  const environment = createEnvironmentMap(scene, renderer);
  createStudioLights(scene, {
    keyIntensity: 1.1,
  });
  const shadowFloor = createShadowFloor();
  scene.add(shadowFloor);

  let root: THREE.Object3D | null = null;
  try {
    root = await loadScene(url, requestHeaders);
    scene.add(root);
    placeShadowFloor(shadowFloor, root);
    fitCameraToObject(camera, root, null, width / height);
    renderer.render(scene, camera);
    return renderer.domElement.toDataURL("image/png");
  } finally {
    if (root) {
      scene.remove(root);
      disposeObject(root);
    }
    environment.dispose();
    renderer.dispose();
  }
}
