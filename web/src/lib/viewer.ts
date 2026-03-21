import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { sleep } from "@/lib/utils";

const DEFAULT_BACKGROUND = "#2a2a2a";
const THUMBNAIL_BACKGROUND = "#2a2a2a";
const MODEL_CACHE_NAME = "app-model-artifacts-v1";
const MODEL_ETAG_STORAGE_KEY_PREFIX = "app:model-etag:";
const loader = new GLTFLoader();

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
    throw new Error("模型边界无效");
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

function createShadowKeyLight(
  scene: THREE.Scene,
  {
    keyIntensity = 1.25,
    castShadow = true,
  }: {
    keyIntensity?: number;
    castShadow?: boolean;
  } = {},
) {
  const key = new THREE.DirectionalLight(0xffffff, keyIntensity);
  key.position.set(4.5, 9.5, 7.5);
  key.castShadow = castShadow;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.near = 0.5;
  key.shadow.camera.far = 60;
  key.shadow.bias = -0.00012;
  scene.add(key);
  return key;
}

function createEnvironmentMap(scene: THREE.Scene, renderer: THREE.WebGLRenderer) {
  const pmremGenerator = new THREE.PMREMGenerator(renderer);
  pmremGenerator.compileCubemapShader();

  const roomEnvironment = new RoomEnvironment();
  const accentLights = [
    { color: "#7ad4ff", intensity: 50 },
    { color: "#8ce8ff", intensity: 50 },
    { color: "#f8c96a", intensity: 18 },
    { color: "#7f8eff", intensity: 43 },
    { color: "#ff9b72", intensity: 22 },
    { color: "#ffffff", intensity: 100 },
  ];
  let accentIndex = 0;

  roomEnvironment.traverse((object: THREE.Object3D) => {
    if (!(object as THREE.Mesh).isMesh) {
      return;
    }
    const material = (object as THREE.Mesh).material;
    if (!(material instanceof THREE.MeshBasicMaterial)) {
      return;
    }
    const preset = accentLights[Math.min(accentIndex, accentLights.length - 1)];
    material.color.set(preset.color).multiplyScalar(preset.intensity);
    accentIndex += 1;
  });

  const envMap = pmremGenerator.fromScene(roomEnvironment, 0.05).texture;
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
      opacity: 0.26,
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  floor.visible = false;
  return floor;
}

function placeShadowFloor(floor: THREE.Mesh, object: THREE.Object3D) {
  const { box, center, maxDim } = getObjectBounds(object);
  const floorSize = Math.max(maxDim * 2.6, 4);
  floor.scale.set(floorSize, floorSize, 1);
  floor.position.set(center.x, box.min.y - 0.002, center.z);
  floor.visible = true;
}

function createGridHelper(primaryColor: string, secondaryColor: string) {
  const grid = new THREE.GridHelper(4, 16, primaryColor, secondaryColor);
  const materials = Array.isArray(grid.material) ? grid.material : [grid.material];
  materials.forEach((material) => {
    material.transparent = true;
    material.opacity = 0.3;
    material.depthWrite = false;
  });
  grid.visible = false;
  return grid;
}

function placeGridHelper(grid: THREE.GridHelper, object: THREE.Object3D) {
  const { box, center, maxDim } = getObjectBounds(object);
  const gridSize = Math.max(maxDim * 3, 4);
  grid.scale.setScalar(gridSize / 4);
  grid.position.set(center.x, box.min.y + 0.001, center.z);
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
  const { size, center, maxDim } = getObjectBounds(object);
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
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.04;
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
    onStatus?.("正在读取本地缓存…");
    const blob = await cachedResponse.blob();
    onStatus?.("模型数据已读取，正在解析…");
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
        ? `正在接收模型数据… ${formatBytes(totalBytes)}`
        : "正在接收模型数据…",
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
        onStatus?.(`正在下载模型… ${percent}%`);
      } else {
        onStatus?.(`正在接收模型数据… ${formatBytes(receivedBytes)}`);
      }
    }
  } finally {
    reader.releaseLock();
  }

  onStatus?.("模型数据已接收，正在解析…");
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
    throw new Error(`模型文件请求失败：${response.status} ${response.statusText}`);
  }
  const totalBytes = Number(response.headers.get("content-length") || 0);
  onStatus?.(
    totalBytes > 0
      ? `正在下载模型… 0%（${formatBytes(totalBytes)}）`
      : "正在接收模型数据…",
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
      onStatus?.(attempt === 1 ? "正在请求模型…" : `正在重试请求模型（${attempt}/3）…`);
      objectUrl = await fetchModelBlobUrl(url, requestHeaders, onStatus);
      onStatus?.("正在解析模型结构…");
      const gltf = await loader.loadAsync(objectUrl);
      const root = gltf.scene || gltf.scenes?.[0];
      if (!root) {
        throw new Error("模型文件内容不完整");
      }
      onStatus?.("正在准备视图…");
      root.traverse((child: any) => {
        if (child.isMesh && child.material) {
          child.castShadow = true;
          child.receiveShadow = true;
          const materials = Array.isArray(child.material) ? child.material : [child.material];
          materials.forEach((material: any) => {
            material.side = THREE.FrontSide;
            if (typeof material.envMapIntensity === "number") {
              material.envMapIntensity = Math.max(material.envMapIntensity, 1.75);
            }
            if (material.isMeshStandardMaterial || material.isMeshPhysicalMaterial) {
              if (typeof material.roughness === "number") {
                material.roughness = Math.min(material.roughness, 0.58);
              }
              if (typeof material.metalness === "number") {
                material.metalness = Math.max(material.metalness, 0.12);
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
  throw lastError || new Error("模型加载失败");
}

function formatViewerErrorMessage(error: unknown) {
  if (error instanceof Error) {
    const detail = error.message.trim();
    if (!detail) {
      return "模型预览加载失败";
    }
    return detail.startsWith("模型") ? detail : `模型预览加载失败：${detail}`;
  }
  return "模型预览加载失败";
}

export class Viewer3D {
  container: HTMLElement;
  options: {
    background: string;
    autoRotate: boolean;
    shadowFloor: boolean;
    showGrid: boolean;
    lightingEnabled: boolean;
    gridPrimaryColor: string;
    gridSecondaryColor: string;
  };
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  modelRoot: THREE.Object3D | null;
  shadowFloor: THREE.Mesh | null;
  gridHelper: THREE.GridHelper;
  keyLight: THREE.DirectionalLight;
  environmentTexture: THREE.Texture | null;
  disposeEnvironment: (() => void) | null;
  gridVisible: boolean;
  lightingEnabled: boolean;
  frameHandle = 0;
  loadToken = 0;
  overlay: HTMLDivElement;
  resizeObserver: ResizeObserver;

  constructor(
    container: HTMLElement,
    options: {
      background?: string;
      autoRotate?: boolean;
      shadowFloor?: boolean;
      showGrid?: boolean;
      lightingEnabled?: boolean;
      gridPrimaryColor?: string;
      gridSecondaryColor?: string;
    } = {},
  ) {
    this.container = container;
    this.options = {
      background: options.background || DEFAULT_BACKGROUND,
      autoRotate: Boolean(options.autoRotate),
      shadowFloor: options.shadowFloor !== false,
      showGrid: Boolean(options.showGrid),
      lightingEnabled: options.lightingEnabled !== false,
      gridPrimaryColor: options.gridPrimaryColor || "rgba(189, 200, 206, 0.3)",
      gridSecondaryColor: options.gridSecondaryColor || "rgba(8, 145, 178, 0.2)",
    };
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
    this.shadowFloor = this.options.shadowFloor ? createShadowFloor() : null;
    this.gridHelper = createGridHelper(this.options.gridPrimaryColor, this.options.gridSecondaryColor);
    this.keyLight = new THREE.DirectionalLight(0xffffff, 1.25);
    this.environmentTexture = null;
    this.disposeEnvironment = null;
    this.gridVisible = this.options.showGrid;
    this.lightingEnabled = this.options.lightingEnabled;

    this.container.innerHTML = "";
    this.renderer.domElement.className = "size-full";
    this.container.appendChild(this.renderer.domElement);

    this.overlay = document.createElement("div");
    this.overlay.className = "absolute inset-0 flex items-center justify-center bg-[color:color-mix(in_srgb,var(--surface-container-lowest)_74%,transparent)] backdrop-blur-[1px]";
    this.overlay.style.display = "none";
    this.container.appendChild(this.overlay);

    this.scene.background = new THREE.Color(this.options.background);
    this.keyLight = createShadowKeyLight(this.scene);
    const environment = createEnvironmentMap(this.scene, this.renderer);
    this.environmentTexture = environment.texture;
    this.disposeEnvironment = environment.dispose;
    if (this.shadowFloor) {
      this.scene.add(this.shadowFloor);
    }
    this.scene.add(this.gridHelper);
    this.setLightingEnabled(this.lightingEnabled);
    this.setGridVisible(this.gridVisible);
    this.camera.position.set(2.5, 1.8, 2.5);
    this.controls.update();

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

  setBackground(background: string) {
    if (!background || background === this.options.background) {
      return;
    }
    this.options.background = background;
    this.scene.background = new THREE.Color(background);
    this.renderer.render(this.scene, this.camera);
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
    previousGrid.geometry.dispose();
    const previousMaterials = Array.isArray(previousGrid.material)
      ? previousGrid.material
      : [previousGrid.material];
    previousMaterials.forEach((material) => material.dispose());

    this.gridHelper = createGridHelper(nextPrimaryColor, nextSecondaryColor);
    this.scene.add(this.gridHelper);
    this.setGridVisible(this.gridVisible);
    this.renderer.render(this.scene, this.camera);
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

  setLightingEnabled(enabled: boolean) {
    this.lightingEnabled = enabled;
    this.keyLight.visible = enabled;
    this.scene.environment = enabled ? this.environmentTexture : null;
    this.renderer.toneMappingExposure = enabled ? 1.04 : 0.86;
    if (this.shadowFloor) {
      this.shadowFloor.visible = enabled && Boolean(this.modelRoot);
      if (enabled && this.modelRoot) {
        placeShadowFloor(this.shadowFloor, this.modelRoot);
      }
    }
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
    this.renderer.render(this.scene, this.camera);
  }

  clearModel() {
    if (!this.modelRoot) {
      this.gridHelper.visible = false;
      if (this.shadowFloor) {
        this.shadowFloor.visible = false;
      }
      return;
    }
    this.scene.remove(this.modelRoot);
    disposeObject(this.modelRoot);
    this.modelRoot = null;
    this.gridHelper.visible = false;
    if (this.shadowFloor) {
      this.shadowFloor.visible = false;
    }
  }

  async load(url?: string | null, requestHeaders: Record<string, string> = {}) {
    if (!url) {
      this.clearModel();
      if (this.shadowFloor) {
        this.shadowFloor.visible = false;
      }
      this.gridHelper.visible = false;
      this.setMessage("模型尚未就绪");
      return null;
    }

    const currentToken = ++this.loadToken;
    this.setMessage("正在请求模型…", "loading");
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
      this.scene.add(root);
      if (this.shadowFloor && this.lightingEnabled) {
        placeShadowFloor(this.shadowFloor, root);
      }
      if (this.gridVisible) {
        placeGridHelper(this.gridHelper, root);
      }
      fitCameraToObject(
        this.camera,
        root,
        this.controls,
        Math.max(this.container.clientWidth, 1) / Math.max(this.container.clientHeight, 1),
      );
      this.overlay.hidden = true;
      this.overlay.style.display = "none";
      this.renderer.render(this.scene, this.camera);
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
    this.gridHelper.geometry.dispose();
    const gridMaterials = Array.isArray(this.gridHelper.material) ? this.gridHelper.material : [this.gridHelper.material];
    gridMaterials.forEach((material) => material.dispose());
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
  createShadowKeyLight(scene, {
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
