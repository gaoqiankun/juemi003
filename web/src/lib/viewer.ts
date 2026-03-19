import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { sleep } from "@/lib/utils";

const DEFAULT_BACKGROUND = "#2a2a2a";
const THUMBNAIL_BACKGROUND = "#2a2a2a";
const loader = new GLTFLoader();

function getObjectBounds(object: THREE.Object3D) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  return { box, size, center, maxDim };
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

  return () => {
    scene.environment = null;
    envMap.dispose();
    roomEnvironment.dispose();
    pmremGenerator.dispose();
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

async function fetchModelBlobUrl(url: string, requestHeaders: Record<string, string> = {}) {
  const response = await fetch(url, {
    headers: requestHeaders,
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`模型文件请求失败：${response.status} ${response.statusText}`);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

async function loadScene(url: string, requestHeaders: Record<string, string> = {}) {
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    let objectUrl = "";
    try {
      objectUrl = await fetchModelBlobUrl(url, requestHeaders);
      const gltf = await loader.loadAsync(objectUrl);
      const root = gltf.scene || gltf.scenes?.[0];
      if (!root) {
        throw new Error("模型文件内容不完整");
      }
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
      return root;
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

export class Viewer3D {
  container: HTMLElement;
  options: { background: string; autoRotate: boolean; shadowFloor: boolean };
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  modelRoot: THREE.Object3D | null;
  shadowFloor: THREE.Mesh | null;
  disposeEnvironment: (() => void) | null;
  frameHandle = 0;
  loadToken = 0;
  overlay: HTMLDivElement;
  resizeObserver: ResizeObserver;

  constructor(container: HTMLElement, options: { background?: string; autoRotate?: boolean; shadowFloor?: boolean } = {}) {
    this.container = container;
    this.options = {
      background: options.background || DEFAULT_BACKGROUND,
      autoRotate: Boolean(options.autoRotate),
      shadowFloor: options.shadowFloor !== false,
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
    this.disposeEnvironment = null;

    this.container.innerHTML = "";
    this.renderer.domElement.className = "size-full";
    this.container.appendChild(this.renderer.domElement);

    this.overlay = document.createElement("div");
    this.overlay.className = "absolute inset-0 flex items-center justify-center bg-black/20 backdrop-blur-[1px]";
    this.overlay.style.display = "none";
    this.container.appendChild(this.overlay);

    this.scene.background = new THREE.Color(this.options.background);
    createShadowKeyLight(this.scene);
    this.disposeEnvironment = createEnvironmentMap(this.scene, this.renderer);
    if (this.shadowFloor) {
      this.scene.add(this.shadowFloor);
    }
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
      ? "border-white/12 bg-black/70 text-white"
      : tone === "loading"
        ? "border-white/12 bg-black/70 text-white"
        : "border-white/12 bg-black/60 text-white/80";
    this.overlay.hidden = false;
    this.overlay.style.display = "flex";
    this.overlay.innerHTML = `<div class="rounded-full border px-4 py-2 text-sm ${toneClass}">${message}</div>`;
  }

  clearModel() {
    if (!this.modelRoot) {
      return;
    }
    this.scene.remove(this.modelRoot);
    disposeObject(this.modelRoot);
    this.modelRoot = null;
  }

  async load(url?: string | null, requestHeaders: Record<string, string> = {}) {
    if (!url) {
      this.clearModel();
      if (this.shadowFloor) {
        this.shadowFloor.visible = false;
      }
      this.setMessage("模型尚未就绪");
      return;
    }

    const currentToken = ++this.loadToken;
    this.overlay.hidden = true;
    this.overlay.style.display = "none";
    let root: THREE.Object3D | null = null;
    try {
      root = await loadScene(url, requestHeaders);
      if (currentToken !== this.loadToken) {
        disposeObject(root);
        return;
      }
      this.clearModel();
      this.modelRoot = root;
      this.scene.add(root);
      if (this.shadowFloor) {
        placeShadowFloor(this.shadowFloor, root);
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
    } catch (error) {
      if (root) {
        disposeObject(root);
      }
      this.clearModel();
      if (this.shadowFloor) {
        this.shadowFloor.visible = false;
      }
      this.setMessage("模型预览加载失败", "error");
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
  const disposeEnvironment = createEnvironmentMap(scene, renderer);
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
    disposeEnvironment();
    renderer.dispose();
  }
}
