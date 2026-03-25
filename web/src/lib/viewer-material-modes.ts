import * as THREE from "three";

import {
  ORIGINAL_MATERIAL_KEY,
  OVERRIDE_MATERIAL_KEY,
  WIREFRAME_OVERLAY_KEY,
  type ViewerDisplayMode,
} from "./viewer-types";
import { disposeMaterialSet } from "./viewer-object-utils";

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

export function buildDisplayModeMaterial(
  original: THREE.Material | THREE.Material[],
  mode: ViewerDisplayMode,
): THREE.Material | THREE.Material[] {
  const originals = Array.isArray(original) ? original : [original];
  const next = originals.map((material) => createDisplayModeMaterial(material, mode));
  return Array.isArray(original) ? next : next[0];
}

export function disposeWireframeOverlay(overlay: THREE.Object3D | null | undefined) {
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

export function addWireframeOverlay(mesh: THREE.Mesh) {
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

export function removeWireframeOverlay(mesh: THREE.Mesh) {
  const overlay = mesh.userData[WIREFRAME_OVERLAY_KEY] as THREE.Object3D | undefined;
  if (!overlay) {
    return;
  }
  mesh.remove(overlay);
  disposeWireframeOverlay(overlay);
  delete mesh.userData[WIREFRAME_OVERLAY_KEY];
}

export function restoreOriginalMaterials(root: THREE.Object3D, disposeOverrides = true) {
  root.traverse((child: any) => {
    if (!child.isMesh) {
      return;
    }
    const mesh = child as THREE.Mesh;
    removeWireframeOverlay(mesh);
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

export function applyDisplayModeToModel(root: THREE.Object3D, displayMode: ViewerDisplayMode) {
  root.traverse((child: any) => {
    if (!child.isMesh || !child.material) {
      return;
    }
    const mesh = child as THREE.Mesh;
    const original = (mesh.userData[ORIGINAL_MATERIAL_KEY] as THREE.Material | THREE.Material[] | undefined)
      || (mesh.material as THREE.Material | THREE.Material[]);
    mesh.userData[ORIGINAL_MATERIAL_KEY] = original;
    removeWireframeOverlay(mesh);

    const previousOverride = mesh.userData[OVERRIDE_MATERIAL_KEY] as THREE.Material | THREE.Material[] | undefined;
    if (displayMode === "texture") {
      mesh.material = original;
      if (previousOverride) {
        disposeMaterialSet(previousOverride);
      }
      delete mesh.userData[OVERRIDE_MATERIAL_KEY];
      return;
    }

    const nextOverride = buildDisplayModeMaterial(original, displayMode);
    mesh.material = nextOverride;
    if (previousOverride) {
      disposeMaterialSet(previousOverride);
    }
    mesh.userData[OVERRIDE_MATERIAL_KEY] = nextOverride;
    if (displayMode === "wireframe") {
      addWireframeOverlay(mesh);
    }
  });
}
