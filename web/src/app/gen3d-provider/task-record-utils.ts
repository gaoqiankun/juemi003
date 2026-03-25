import {
  ACTIVE_STATUSES,
  defaultProgressForStatus,
  formatTaskStatus,
} from "@/lib/format";
import type {
  ArtifactPayload,
  TaskEventRecord,
  TaskRecord,
  TaskStatus,
} from "@/lib/types";

export function isActiveStatus(status?: string): status is TaskStatus {
  return ACTIVE_STATUSES.has((status || "") as TaskStatus);
}

export function normalizeTaskRecord(task: Partial<TaskRecord> & Record<string, unknown>): TaskRecord {
  const taskId = String(task.taskId || task.task_id || "").trim();
  const status = String(task.status || task.statusLabel || task.status_label || "submitted") as TaskStatus;
  const createdAt = String(task.createdAt || task.created_at || task.submittedAt || task.submitted_at || new Date().toISOString());
  const updatedAt = String(task.updatedAt || task.updated_at || task.finishedAt || task.finished_at || createdAt);
  const artifacts = Array.isArray(task.artifacts) ? (task.artifacts as ArtifactPayload[]) : [];
  const queuePosition = typeof task.queuePosition === "number"
    ? task.queuePosition
    : typeof task.queue_position === "number"
      ? task.queue_position
      : null;
  const estimatedWaitSeconds = typeof task.estimatedWaitSeconds === "number"
    ? task.estimatedWaitSeconds
    : typeof task.estimated_wait_seconds === "number"
      ? task.estimated_wait_seconds
      : null;
  const estimatedFinishAt = typeof task.estimatedFinishAt === "string"
    ? task.estimatedFinishAt
    : typeof task.estimated_finish_at === "string"
      ? task.estimated_finish_at
      : null;

  return {
    taskId,
    model: String(task.model || "trellis"),
    inputUrl: String(task.inputUrl || task.input_url || ""),
    createdAt,
    submittedAt: String(task.submittedAt || task.submitted_at || createdAt),
    updatedAt,
    lastSeenAt: String(task.lastSeenAt || task.last_seen_at || updatedAt),
    status,
    statusLabel: String(task.statusLabel || task.status_label || formatTaskStatus(status)),
    progress: Number.isFinite(task.progress) ? Number(task.progress) : defaultProgressForStatus(status),
    currentStage: String(task.currentStage || task.current_stage || status),
    queuePosition,
    estimatedWaitSeconds,
    estimatedFinishAt,
    artifacts,
    error: task.error || null,
    events: Array.isArray(task.events) ? (task.events as TaskEventRecord[]).slice(-30) : [],
    transport: String(task.transport || "idle"),
    note: String(task.note || ""),
    resolvedArtifactUrl: String(task.resolvedArtifactUrl || task.resolved_artifact_url || ""),
    rawArtifactUrl: String(task.rawArtifactUrl || task.raw_artifact_url || ""),
    previewDataUrl: String(task.previewDataUrl || task.preview_data_url || ""),
    thumbnailUrl: String(task.thumbnailUrl || task.thumbnail_url || ""),
    thumbnailState: (task.thumbnailState || task.thumbnail_state || "idle") as TaskRecord["thumbnailState"],
    pendingDelete: Boolean(task.pendingDelete),
    pendingCancel: Boolean(task.pendingCancel),
    successRefreshScheduled: Boolean(task.successRefreshScheduled),
  };
}

export function resolveArtifactUrl(url: string | null | undefined, baseUrl: string) {
  const raw = String(url || "").trim();
  if (!raw) {
    return "";
  }
  if (raw.startsWith("/")) {
    const normalizedBase = String(baseUrl || "").replace(/\/+$/, "");
    return normalizedBase ? `${normalizedBase}${raw}` : raw;
  }
  return raw;
}

export function buildLocalArtifactCandidates(taskId: string, fileUrl: string, baseUrl: string) {
  let fileName = "model.glb";
  try {
    const path = decodeURIComponent(new URL(fileUrl).pathname);
    const parts = path.split("/").filter(Boolean);
    fileName = parts[parts.length - 1] || fileName;
  } catch {
    // ignore malformed file paths
  }

  const normalizedBase = String(baseUrl || "").replace(/\/+$/, "");
  if (!normalizedBase) {
    return [];
  }

  const root = `${normalizedBase}/`;
  return Array.from(new Set([
    new URL(`artifacts/${encodeURIComponent(taskId)}/${encodeURIComponent(fileName)}`, root).toString(),
    new URL(`v1/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(fileName)}`, root).toString(),
    new URL(`${encodeURIComponent(taskId)}/${encodeURIComponent(fileName)}`, new URL("artifacts/", root)).toString(),
  ]));
}

export async function probeUrl(url: string) {
  try {
    const response = await fetch(url, { method: "HEAD", cache: "no-store" });
    if (response.ok) {
      return true;
    }
    if (response.status === 405) {
      const fallback = await fetch(url, { cache: "no-store" });
      return fallback.ok;
    }
    return false;
  } catch {
    return false;
  }
}
