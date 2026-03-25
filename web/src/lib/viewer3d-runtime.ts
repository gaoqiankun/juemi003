import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import i18n from "@/i18n";

import {
  applyStudioLightAngle,
  applyStudioLightIntensity,
  createEnvironmentMap,
  createStudioLights,
  type StudioLights,
} from "./viewer-lighting-env";
import {
  applyDisplayModeToModel,
  restoreOriginalMaterials,
} from "./viewer-material-modes";
import {
  formatViewerErrorMessage,
  loadScene,
} from "./viewer-model-loader";
import {
  disposeObject,
  fitCameraToObject,
  getModelStats,
} from "./viewer-object-utils";
import {
  createRadialGradientTexture,
  createRenderer,
  easeOutCubic,
} from "./viewer-render-utils";
import {
  createContactShadow,
  createGridHelper,
  createShadowFloor,
  disposeGridHelper,
  placeContactShadow,
  placeGridHelper,
  placeShadowFloor,
} from "./viewer-floor-grid";
import {
  DEFAULT_BACKGROUND,
  VIEWER_LIGHT_ANGLE_DEFAULT,
  VIEWER_LIGHT_ANGLE_MAX,
  VIEWER_LIGHT_ANGLE_MIN,
  VIEWER_LIGHT_INTENSITY_DEFAULT,
  VIEWER_LIGHT_INTENSITY_MAX,
  VIEWER_LIGHT_INTENSITY_MIN,
  type ViewerDisplayMode,
} from "./viewer-types";

function tv(key: string, options?: Record<string, unknown>) {
  return i18n.t(key, options) as string;
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

  private applyDisplayModeToModel() {
    if (!this.modelRoot) {
      return;
    }
    applyDisplayModeToModel(this.modelRoot, this.displayMode);
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
    restoreOriginalMaterials(this.modelRoot, true);
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
        return null;
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
