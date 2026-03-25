import { useCallback, useEffect, type MutableRefObject } from "react";
import { toast } from "sonner";

import {
  fetchHealth,
  fetchTaskList,
  normalizeBaseUrl,
} from "@/lib/api";
import { compareTaskRecords } from "@/lib/format";
import type {
  ApiConfig,
  ConnectionState,
  TaskListPayload,
  TaskPageState,
  TaskRecord,
  TaskSummaryPayload,
} from "@/lib/types";

import { isActiveStatus } from "./task-record-utils";

export function useConfigBootstrap({
  config,
  configRef,
  setConnection,
  persistConfig,
  taskPageRef,
  tasksRef,
  updateTaskPage,
  replaceTasksFromServer,
  subscribeToTask,
  resetTaskState,
}: {
  config: ApiConfig;
  configRef: MutableRefObject<ApiConfig>;
  setConnection: (next: ConnectionState | ((previous: ConnectionState) => ConnectionState)) => void;
  persistConfig: (next: Partial<ApiConfig>) => void;
  taskPageRef: MutableRefObject<TaskPageState>;
  tasksRef: MutableRefObject<Record<string, TaskRecord>>;
  updateTaskPage: (updater: (previous: TaskPageState) => TaskPageState) => void;
  replaceTasksFromServer: (taskSummaries: TaskSummaryPayload[], append?: boolean) => Promise<void>;
  subscribeToTask: (taskId: string, force?: boolean) => Promise<void>;
  resetTaskState: () => void;
}) {
  const pingHealthAction = useCallback(async (silent = false) => {
    try {
      const payload = await fetchHealth(configRef.current);
      setConnection({
        tone: "ready",
        label: "已连接",
        detail: "服务正常",
      });
      if (!silent) {
        toast.success("已连接", {
          description: "服务正常。",
        });
      }
      return payload;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setConnection({
        tone: "error",
        label: "连接失败",
        detail: message,
      });
      if (!silent) {
        toast.error("连接失败", {
          description: message,
        });
      }
      throw error;
    }
  }, [configRef, setConnection]);

  const refreshTaskListAction = useCallback(async ({ append = false, resubscribe = false, silent = false } = {}) => {
    if (!configRef.current.baseUrl) {
      throw new Error("请先填写服务地址");
    }
    if (!configRef.current.token) {
      setConnection((previous) => ({
        ...previous,
        tone: "empty",
        label: "等待连接",
        detail: "请先到设置页填写连接信息",
      }));
      resetTaskState();
      return;
    }

    updateTaskPage((previous) => ({ ...previous, isLoading: true }));
    try {
      const payload = await fetchTaskList(configRef.current, append ? taskPageRef.current.nextCursor : "", taskPageRef.current.limit) as TaskListPayload;
      await replaceTasksFromServer(Array.isArray(payload.items) ? payload.items : [], append);
      updateTaskPage((previous) => ({
        ...previous,
        nextCursor: String(payload.nextCursor || payload.next_cursor || ""),
        hasMore: Boolean(payload.hasMore ?? payload.has_more),
      }));
      if (resubscribe) {
        const sorted = Object.values(tasksRef.current).sort(compareTaskRecords);
        for (const task of sorted) {
          if (isActiveStatus(task.status)) {
            await subscribeToTask(task.taskId, true);
          }
        }
      }
      if (!silent) {
        toast.success(append ? "更多内容已加载" : "图库已刷新", {
          description: `当前共有 ${Object.keys(tasksRef.current).length} 条内容。`,
        });
      }
    } finally {
      updateTaskPage((previous) => ({ ...previous, isLoading: false }));
    }
  }, [configRef, replaceTasksFromServer, resetTaskState, setConnection, subscribeToTask, taskPageRef, tasksRef, updateTaskPage]);

  const saveConfig = useCallback(async (next: Partial<ApiConfig>) => {
    persistConfig(next);
    const merged = {
      baseUrl: normalizeBaseUrl(next.baseUrl ?? configRef.current.baseUrl),
      token: String(next.token ?? configRef.current.token).trim(),
    };
    configRef.current = merged;

    if (!merged.token) {
      setConnection({
        tone: "empty",
        label: "等待连接",
        detail: "请先到设置页填写连接信息",
      });
      resetTaskState();
      toast.success("已保存", {
        description: "连接信息已更新。",
      });
      return;
    }

    toast.success("已保存", {
      description: "连接信息已更新，正在后台验证连接并刷新内容。",
    });

    void (async () => {
      const [healthResult, refreshResult] = await Promise.allSettled([
        pingHealthAction(true),
        refreshTaskListAction({ append: false, resubscribe: true, silent: true }),
      ]);

      if (refreshResult.status === "rejected") {
        toast.error("后台刷新失败", {
          description: refreshResult.reason instanceof Error ? refreshResult.reason.message : String(refreshResult.reason),
        });
        return;
      }

      if (healthResult.status === "rejected") {
        toast.error("连接验证失败", {
          description: healthResult.reason instanceof Error ? healthResult.reason.message : String(healthResult.reason),
        });
        return;
      }

      toast.success("同步完成", {
        description: "连接验证和内容刷新已完成。",
      });
    })();
  }, [configRef, persistConfig, pingHealthAction, refreshTaskListAction, resetTaskState, setConnection]);

  useEffect(() => {
    if (config.baseUrl) {
      pingHealthAction(true).catch(() => undefined);
    }
    if (config.baseUrl && config.token) {
      refreshTaskListAction({ append: false, resubscribe: true, silent: true }).catch((error) => {
        toast.error("加载失败", {
          description: error instanceof Error ? error.message : String(error),
        });
      });
    }
  }, [config.baseUrl, config.token, pingHealthAction, refreshTaskListAction]);

  return {
    pingHealthAction,
    refreshTaskListAction,
    saveConfig,
  };
}
