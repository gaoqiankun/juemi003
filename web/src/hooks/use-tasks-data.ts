import { useEffect, useState } from "react";

import type { TaskOverviewMetric, TaskStatus } from "@/data/admin-mocks";
import {
  fetchAdminTasks,
  fetchTasksStats,
  type RawAdminTaskSummary,
  type RawAdminTasksResponse,
} from "@/lib/admin-api";

export interface AdminTaskItem {
  id: string;
  model: string;
  status: TaskStatus;
  createdAt: string;
  latencySeconds: number;
  owner: string;
}

function toOwnerLabel(
  keyId: string,
  keyLabel: string,
  ownerFallback: string,
) {
  const normalizedLabel = String(keyLabel || "").trim();
  if (normalizedLabel) {
    return normalizedLabel;
  }
  const normalizedOwnerFallback = String(ownerFallback || "").trim();
  if (normalizedOwnerFallback) {
    return normalizedOwnerFallback;
  }
  const normalizedKeyId = String(keyId || "").trim();
  if (!normalizedKeyId) {
    return "-";
  }
  return `${normalizedKeyId.slice(0, 8)}${normalizedKeyId.length > 8 ? "…" : ""}`;
}

export interface TasksDataResult {
  overview: TaskOverviewMetric[];
  tasks: AdminTaskItem[];
}

function mapTaskStatus(status: string): TaskStatus {
  const normalized = status.toLowerCase();
  if (normalized === "succeeded" || normalized === "completed") {
    return "completed";
  }
  if (normalized === "failed" || normalized === "cancelled") {
    return "failed";
  }
  if (normalized === "queued" || normalized === "preprocessing" || normalized === "gpu_queued") {
    return "queued";
  }
  return "live";
}

function parseLatencySeconds(createdAt: string, finishedAt?: string | null) {
  if (!finishedAt) {
    return 0;
  }
  const created = new Date(createdAt);
  const finished = new Date(finishedAt);
  if (Number.isNaN(created.getTime()) || Number.isNaN(finished.getTime())) {
    return 0;
  }
  return Math.max(0, Math.round((finished.getTime() - created.getTime()) / 1000));
}

function mapTask(item: RawAdminTaskSummary): AdminTaskItem | null {
  const id = String(item.taskId || item.task_id || "").trim();
  if (!id) {
    return null;
  }
  const createdAt = String(item.createdAt || item.created_at || new Date().toISOString());
  const status = mapTaskStatus(String(item.status || "queued"));
  const finishedAt = item.finishedAt ?? item.finished_at ?? null;
  const keyId = String(item.keyId || item.key_id || "").trim();
  const keyLabel = String(item.keyLabel || item.key_label || "").trim();
  const ownerFallback = String(item.owner || "").trim();
  return {
    id,
    model: String(item.model || "-"),
    status,
    createdAt,
    latencySeconds: parseLatencySeconds(createdAt, finishedAt),
    owner: toOwnerLabel(keyId, keyLabel, ownerFallback),
  };
}

function normalizeTasksResponse(payload: RawAdminTasksResponse): AdminTaskItem[] {
  const source = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload.tasks)
      ? payload.tasks
      : [];
  return source
    .map(mapTask)
    .filter((item): item is AdminTaskItem => item !== null);
}

export function useTasksData() {
  const [data, setData] = useState<TasksDataResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchTasksStats(), fetchAdminTasks()])
      .then(([statsRes, tasksRes]) => {
        setData({
          overview: statsRes.overview,
          tasks: normalizeTasksResponse(tasksRes),
        });
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
