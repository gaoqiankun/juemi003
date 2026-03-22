import { useEffect, useState } from "react";

import type { QueueTask, TaskOverviewMetric, TaskLogEntry } from "@/data/admin-mocks";
import {
  fetchAdminTasks,
  fetchTasksStats,
  type RawAdminTaskSummary,
  type RawAdminTasksResponse,
} from "@/lib/admin-api";

export interface TasksDataResult {
  overview: TaskOverviewMetric[];
  tasks: QueueTask[];
  logs: TaskLogEntry[];
}

function mapTaskStatus(status: string): QueueTask["status"] {
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

function mapTask(item: RawAdminTaskSummary): QueueTask {
  const createdAt = String(item.createdAt || item.created_at || new Date().toISOString());
  const status = mapTaskStatus(String(item.status || "queued"));
  const finishedAt = item.finishedAt ?? item.finished_at ?? null;
  return {
    id: String(item.taskId || item.task_id || ""),
    subjectKey: "subjects.sneaker",
    model: String(item.model || "trellis"),
    status,
    progress: status === "completed" ? 100 : status === "failed" ? 100 : status === "live" ? 60 : 0,
    queue: "default",
    createdAt,
    latencySeconds: parseLatencySeconds(createdAt, finishedAt),
    owner: String(item.keyId || item.key_id || "-"),
  };
}

function normalizeTasksResponse(payload: RawAdminTasksResponse): QueueTask[] {
  const source = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload.tasks)
      ? payload.tasks
      : [];
  return source.map(mapTask);
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
          logs: [], // logs are not provided by the API
        });
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
