import { useEffect, useState } from "react";

import type { QueueTask, TaskOverviewMetric, TaskLogEntry } from "@/data/admin-mocks";
import { fetchAdminTasks, fetchTasksStats } from "@/lib/admin-api";

export interface TasksDataResult {
  overview: TaskOverviewMetric[];
  tasks: QueueTask[];
  logs: TaskLogEntry[];
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
          tasks: tasksRes.tasks,
          logs: [], // logs are not provided by the API
        });
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}
