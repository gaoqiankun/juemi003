import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

import {
  VIEWER_LIGHT_ANGLE_DEFAULT,
  VIEWER_LIGHT_INTENSITY_MAX,
  VIEWER_LIGHT_INTENSITY_MIN,
} from "./viewer-types";

export interface StudioLights {
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

export function applyStudioLightIntensity(lights: StudioLights, gain: number) {
  const normalizedGain = THREE.MathUtils.clamp(gain, VIEWER_LIGHT_INTENSITY_MIN, VIEWER_LIGHT_INTENSITY_MAX);
  lights.key.intensity = STUDIO_LIGHT_BASE.key.intensity * normalizedGain;
  lights.rim.intensity = STUDIO_LIGHT_BASE.rim.intensity * normalizedGain;
  lights.fill.intensity = STUDIO_LIGHT_BASE.fill.intensity * normalizedGain;
}

export function applyStudioLightAngle(lights: StudioLights, angleDeg: number) {
  const normalizedAngle = ((angleDeg % 360) + 360) % 360;
  lights.rig.rotation.y = THREE.MathUtils.degToRad(normalizedAngle);
}

export function createStudioLights(
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
  applyStudioLightIntensity(lights, initialGain);
  return lights;
}

export function createEnvironmentMap(scene: THREE.Scene, renderer: THREE.WebGLRenderer) {
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
