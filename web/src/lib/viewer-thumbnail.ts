import * as THREE from "three";

import {
  createEnvironmentMap,
  createStudioLights,
} from "./viewer-lighting-env";
import {
  disposeObject,
  fitCameraToObject,
} from "./viewer-object-utils";
import { createRenderer } from "./viewer-render-utils";
import {
  createShadowFloor,
  placeShadowFloor,
} from "./viewer-floor-grid";
import { loadScene } from "./viewer-model-loader";
import { THUMBNAIL_BACKGROUND } from "./viewer-types";

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
