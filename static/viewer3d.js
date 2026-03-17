import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const DEFAULT_BACKGROUND = "#060816";
const THUMBNAIL_BACKGROUND = "#0d1222";
const loader = new GLTFLoader();

function disposeMaterial(material) {
  if (!material) {
    return;
  }
  Object.values(material).forEach((value) => {
    if (value && value.isTexture) {
      value.dispose();
    }
  });
  material.dispose();
}

function disposeObject(root) {
  if (!root) {
    return;
  }
  root.traverse((child) => {
    if (child.geometry) {
      child.geometry.dispose();
    }
    if (Array.isArray(child.material)) {
      child.material.forEach(disposeMaterial);
    } else if (child.material) {
      disposeMaterial(child.material);
    }
  });
}

function createStudioLights(scene) {
  const ambient = new THREE.AmbientLight(0xffffff, 2.6);
  const hemisphere = new THREE.HemisphereLight(0x9fb7ff, 0x0f172a, 1.2);
  const key = new THREE.DirectionalLight(0xffffff, 2.8);
  key.position.set(4, 7, 5);
  const rim = new THREE.DirectionalLight(0x6d8dff, 1.35);
  rim.position.set(-5, 3.5, -4);
  scene.add(ambient, hemisphere, key, rim);
}

function fitCameraToObject(camera, object, controls, aspect = 1) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
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

function createRenderer({ width, height, alpha = false, preserveDrawingBuffer = false }) {
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
  renderer.toneMappingExposure = 1.1;
  renderer.shadowMap.enabled = false;
  return renderer;
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function fetchModelBlobUrl(url, attempt) {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`模型文件请求失败：${response.status} ${response.statusText}`);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

async function loadScene(url) {
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    let objectUrl = "";
    try {
      objectUrl = await fetchModelBlobUrl(url, attempt);
      const gltf = await loader.loadAsync(objectUrl);
      const root = gltf.scene || gltf.scenes?.[0];
      if (!root) {
        throw new Error("GLB did not contain a scene");
      }
      root.traverse((child) => {
        if (child.isMesh) {
          child.castShadow = false;
          child.receiveShadow = false;
          if (child.material) {
            child.material.side = THREE.FrontSide;
          }
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
  constructor(container, options = {}) {
    this.container = container;
    this.options = {
      background: options.background || DEFAULT_BACKGROUND,
      autoRotate: Boolean(options.autoRotate),
    };
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1000);
    this.renderer = createRenderer({
      width: Math.max(this.container.clientWidth, 1),
      height: Math.max(this.container.clientHeight, 1),
      alpha: false,
    });
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.minDistance = 0.4;
    this.controls.maxDistance = 80;
    this.controls.autoRotate = this.options.autoRotate;
    this.controls.autoRotateSpeed = 1.25;

    this.modelRoot = null;
    this.frameHandle = 0;
    this.loadToken = 0;

    this.container.innerHTML = "";
    this.container.classList.add("viewer-3d-shell");
    this.container.style.position = "relative";
    this.renderer.domElement.className = "viewer-3d-canvas";
    this.container.appendChild(this.renderer.domElement);

    this.overlay = document.createElement("div");
    this.overlay.className = "viewer-3d-overlay";
    this.overlay.innerHTML = '<div class="viewer-3d-message">等待选择任务</div>';
    this.container.appendChild(this.overlay);

    this.scene.background = new THREE.Color(this.options.background);
    createStudioLights(this.scene);
    this.camera.position.set(2.5, 1.8, 2.5);
    this.controls.update();
    this.handleResize = this.handleResize.bind(this);
    this.animate = this.animate.bind(this);
    this.resizeObserver = new ResizeObserver(this.handleResize);
    this.resizeObserver.observe(this.container);
    this.handleResize();
    this.animate();
  }

  handleResize() {
    const width = Math.max(this.container.clientWidth, 1);
    const height = Math.max(this.container.clientHeight, 1);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  animate() {
    this.frameHandle = window.requestAnimationFrame(this.animate);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  setMessage(message, tone = "info") {
    this.overlay.dataset.tone = tone;
    this.overlay.hidden = false;
    this.overlay.innerHTML = `<div class="viewer-3d-message">${message}</div>`;
  }

  clearModel() {
    if (!this.modelRoot) {
      return;
    }
    this.scene.remove(this.modelRoot);
    disposeObject(this.modelRoot);
    this.modelRoot = null;
  }

  async load(url) {
    if (!url) {
      this.clearModel();
      this.setMessage("任务产物尚未可用");
      return;
    }

    const currentToken = ++this.loadToken;
    this.setMessage("正在加载 3D 模型…", "loading");

    let root = null;
    try {
      root = await loadScene(url);
      if (currentToken !== this.loadToken) {
        disposeObject(root);
        return;
      }
      this.clearModel();
      this.modelRoot = root;
      this.scene.add(root);
      fitCameraToObject(
        this.camera,
        root,
        this.controls,
        Math.max(this.container.clientWidth, 1) / Math.max(this.container.clientHeight, 1),
      );
      this.overlay.hidden = true;
      this.renderer.render(this.scene, this.camera);
    } catch (error) {
      if (root) {
        disposeObject(root);
      }
      this.clearModel();
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
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
    if (this.overlay.parentNode === this.container) {
      this.container.removeChild(this.overlay);
    }
  }
}

export async function renderModelThumbnail(
  url,
  { width = 480, height = 320, background = THUMBNAIL_BACKGROUND } = {},
) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(background);
  createStudioLights(scene);

  const camera = new THREE.PerspectiveCamera(32, width / height, 0.1, 1000);
  const renderer = createRenderer({
    width,
    height,
    alpha: false,
    preserveDrawingBuffer: true,
  });

  let root = null;
  try {
    root = await loadScene(url);
    scene.add(root);
    fitCameraToObject(camera, root, null, width / height);
    renderer.render(scene, camera);
    return renderer.domElement.toDataURL("image/png");
  } finally {
    if (root) {
      scene.remove(root);
      disposeObject(root);
    }
    renderer.dispose();
  }
}
