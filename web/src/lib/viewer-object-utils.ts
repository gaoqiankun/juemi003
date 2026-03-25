import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import i18n from "@/i18n";

import type { ViewerModelStats } from "./viewer-types";

function tv(key: string, options?: Record<string, unknown>) {
  return i18n.t(key, options) as string;
}

function hasFiniteBox(box: THREE.Box3) {
  return Number.isFinite(box.min.x)
    && Number.isFinite(box.min.y)
    && Number.isFinite(box.min.z)
    && Number.isFinite(box.max.x)
    && Number.isFinite(box.max.y)
    && Number.isFinite(box.max.z);
}

export function getObjectBounds(object: THREE.Object3D) {
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

export function normalizeModelRoot(root: THREE.Object3D) {
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

export function disposeObject(root: THREE.Object3D | null) {
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

export function disposeMaterialSet(material: THREE.Material | THREE.Material[] | undefined | null) {
  if (!material) {
    return;
  }
  const materials = Array.isArray(material) ? material : [material];
  materials.forEach((entry) => {
    entry.dispose();
  });
}

export function getModelStats(object: THREE.Object3D): ViewerModelStats {
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

export function fitCameraToObject(
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
