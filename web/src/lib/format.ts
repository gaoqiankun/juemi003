import { Box, CheckCircle2, Clock3, LoaderCircle, OctagonX } from "lucide-react";

import type { TaskRecord, TaskStatus } from "@/lib/types";

export const TERMINAL_STATUSES = new Set<TaskStatus>(["succeeded", "failed", "cancelled"]);
export const CANCELLABLE_STATUSES = new Set<TaskStatus>(["gpu_queued"]);
export const ACTIVE_STATUSES = new Set<TaskStatus>([
  "submitted",
  "queued",
  "preprocessing",
  "gpu_queued",
  "gpu_ss",
  "gpu_shape",
  "gpu_material",
  "exporting",
  "uploading",
]);

export const STATUS_LABELS: Record<string, string> = {
  submitted: "Submitted",
  queued: "Queued",
  preprocessing: "Preprocessing",
  gpu_queued: "GPU Queued",
  gpu_ss: "Sparse Structure",
  gpu_shape: "Geometry",
  gpu_material: "Material",
  exporting: "Exporting",
  uploading: "Uploading",
  succeeded: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const STAGE_LABELS: Record<string, string> = {
  submitted: "任务已提交，等待排队",
  queued: "在队列中等待 GPU 资源",
  preprocessing: "预处理中：读取并规范化图片",
  gpu_queued: "预处理完成，等待 GPU stage",
  gpu_ss: "Sparse Structure 阶段",
  gpu_shape: "Shape / Geometry 阶段",
  gpu_material: "Material / PBR 阶段",
  exporting: "导出 GLB 产物",
  uploading: "上传 artifact",
  succeeded: "任务已完成",
  failed: "任务执行失败",
  cancelled: "任务已取消",
};

export const DEFAULT_PROGRESS_BY_STATUS: Record<string, number> = {
  submitted: 4,
  queued: 8,
  preprocessing: 18,
  gpu_queued: 28,
  gpu_ss: 42,
  gpu_shape: 62,
  gpu_material: 82,
  exporting: 92,
  uploading: 96,
  succeeded: 100,
  failed: 100,
  cancelled: 0,
};

export function defaultProgressForStatus(status: string) {
  return DEFAULT_PROGRESS_BY_STATUS[status] ?? 0;
}

export function formatTaskStatus(status?: string) {
  return STATUS_LABELS[status || ""] || String(status || "unknown").replace(/_/g, " ");
}

export function formatStage(stage?: string) {
  return STAGE_LABELS[stage || ""] || formatTaskStatus(stage);
}

export function isActiveStatus(status?: string): status is TaskStatus {
  return ACTIVE_STATUSES.has((status || "") as TaskStatus);
}

export function isCancellable(task?: TaskRecord | null) {
  return Boolean(task) && CANCELLABLE_STATUSES.has((task?.status || "") as TaskStatus) && !task?.pendingCancel;
}

export function getVisualStatus(status?: string) {
  if (status === "succeeded") {
    return "done";
  }
  if (status === "failed" || status === "cancelled") {
    return "failed";
  }
  if (status === "submitted" || status === "queued") {
    return "queued";
  }
  return "processing";
}

export function getTaskShortId(taskId?: string) {
  return String(taskId || "").slice(-8) || "--------";
}

export function compareTaskRecords(a: TaskRecord, b: TaskRecord) {
  const timeA = new Date(a.createdAt || a.submittedAt || 0).getTime();
  const timeB = new Date(b.createdAt || b.submittedAt || 0).getTime();
  return timeB - timeA;
}

export function formatTime(value?: string | null) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatRelativeTime(value?: string | null) {
  if (!value) {
    return "刚刚";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  const diffMs = date.getTime() - Date.now();
  const diffMinutes = Math.round(diffMs / 60000);
  const formatter = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
  if (Math.abs(diffMinutes) < 60) {
    return formatter.format(diffMinutes, "minute");
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return formatter.format(diffHours, "hour");
  }
  const diffDays = Math.round(diffHours / 24);
  return formatter.format(diffDays, "day");
}

export const STATUS_ICON = {
  done: CheckCircle2,
  failed: OctagonX,
  queued: Clock3,
  processing: LoaderCircle,
  empty: Box,
};
