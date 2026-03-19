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
  submitted: "准备中",
  queued: "排队中",
  preprocessing: "处理中",
  gpu_queued: "即将开始",
  gpu_ss: "生成中",
  gpu_shape: "生成中",
  gpu_material: "细化中",
  exporting: "整理中",
  uploading: "整理中",
  succeeded: "已完成",
  failed: "生成失败",
  cancelled: "已取消",
};

export const STAGE_LABELS: Record<string, string> = {
  submitted: "正在准备",
  queued: "正在排队",
  preprocessing: "正在处理图片",
  gpu_queued: "即将开始生成",
  gpu_ss: "正在生成中",
  gpu_shape: "正在生成中",
  gpu_material: "正在细化细节",
  exporting: "正在整理模型",
  uploading: "正在整理模型",
  succeeded: "模型已生成",
  failed: "本次生成未完成",
  cancelled: "已取消本次生成",
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
