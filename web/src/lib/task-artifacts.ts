import { buildApiUrl } from "@/lib/api";
import type { TaskRecord } from "@/lib/types";

function getArtifactFileName(task: TaskRecord | null | undefined) {
  const primaryArtifact = task?.artifacts.find((artifact) => artifact.type === "glb") || task?.artifacts[0];
  const sourceUrl = primaryArtifact?.url || task?.rawArtifactUrl || task?.resolvedArtifactUrl || "";
  if (!sourceUrl) {
    return "";
  }
  try {
    const parsed = new URL(sourceUrl, window.location.origin);
    const fileName = parsed.pathname.split("/").filter(Boolean).pop() || "";
    return decodeURIComponent(fileName);
  } catch {
    return "";
  }
}

export function getTaskArtifactProxyUrl(task: TaskRecord | null | undefined, baseUrl?: string) {
  const fallbackUrl = task?.resolvedArtifactUrl || task?.rawArtifactUrl || "";
  if (!task || !baseUrl) {
    return fallbackUrl;
  }
  const fileName = getArtifactFileName(task);
  if (!fileName) {
    return fallbackUrl;
  }
  return buildApiUrl(
    baseUrl,
    `/v1/tasks/${encodeURIComponent(task.taskId)}/artifacts/${encodeURIComponent(fileName)}`,
  );
}
