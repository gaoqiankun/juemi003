import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import i18n from "@/i18n";
import { sleep } from "@/lib/utils";

import { formatBytes } from "./viewer-render-utils";
import { normalizeModelRoot } from "./viewer-object-utils";
import {
  MODEL_CACHE_NAME,
  MODEL_ETAG_STORAGE_KEY_PREFIX,
} from "./viewer-types";

const loader = new GLTFLoader();

function tv(key: string, options?: Record<string, unknown>) {
  return i18n.t(key, options) as string;
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

export async function loadScene(
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

export function formatViewerErrorMessage(error: unknown) {
  if (error instanceof Error) {
    const detail = error.message.trim();
    if (!detail) {
      return tv("user.viewer.runtime.errors.previewFailed");
    }
    return detail;
  }
  return tv("user.viewer.runtime.errors.previewFailed");
}
