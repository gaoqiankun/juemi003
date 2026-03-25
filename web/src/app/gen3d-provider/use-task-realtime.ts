import { useCallback, type MutableRefObject } from "react";

import {
  authHeaders,
  buildApiUrl,
  extractErrorMessage,
  fetchTask,
} from "@/lib/api";
import { TERMINAL_STATUSES } from "@/lib/format";
import type {
  ApiConfig,
  TaskRecord,
  TaskSnapshotPayload,
  TaskStatus,
} from "@/lib/types";

import { POLL_INTERVAL_MS } from "./state-persistence";
import type { SubscriptionHandle } from "./use-task-store";

export function useTaskRealtime({
  configRef,
  tasksRef,
  subscriptionsRef,
  stopSubscription,
  upsertTask,
  refreshTaskAction,
  applyEventPayload,
  applyTaskSnapshot,
}: {
  configRef: MutableRefObject<ApiConfig>;
  tasksRef: MutableRefObject<Record<string, TaskRecord>>;
  subscriptionsRef: MutableRefObject<Map<string, SubscriptionHandle>>;
  stopSubscription: (taskId: string) => void;
  upsertTask: (taskId: string, patch: Record<string, unknown>) => TaskRecord;
  refreshTaskAction: (taskId: string, options?: { silent?: boolean }) => Promise<void>;
  applyEventPayload: (taskId: string, payload: Record<string, unknown>, source: string) => Promise<void>;
  applyTaskSnapshot: (taskId: string, payload: TaskSnapshotPayload, source: string) => Promise<void>;
}) {
  const parseSseEvent = useCallback((rawBlock: string) => {
    if (!rawBlock.trim()) {
      return null;
    }
    let eventName = "";
    const dataLines: string[] = [];
    rawBlock.split("\n").forEach((line) => {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    });
    if (!dataLines.length) {
      return null;
    }
    const payload = JSON.parse(dataLines.join("\n"));
    payload.event = payload.event || eventName;
    return payload;
  }, []);

  const startPolling = useCallback((taskId: string) => {
    stopSubscription(taskId);
    const timer = window.setInterval(() => {
      refreshTaskAction(taskId, { silent: true }).catch((error) => {
        console.warn("polling refresh failed", error);
        upsertTask(taskId, {
          transport: "polling",
          note: "更新失败，请稍后再试。",
        });
      });
    }, POLL_INTERVAL_MS);
    subscriptionsRef.current.set(taskId, { mode: "polling", timer });
  }, [refreshTaskAction, stopSubscription, subscriptionsRef, upsertTask]);

  const connectSse = useCallback(async (taskId: string) => {
    const controller = new AbortController();
    subscriptionsRef.current.set(taskId, {
      mode: "sse",
      controller,
    });
    upsertTask(taskId, {
      transport: "sse",
      note: "正在生成中。",
    });

    const response = await fetch(buildApiUrl(configRef.current.baseUrl, `/v1/tasks/${encodeURIComponent(taskId)}/events`), {
      headers: authHeaders(configRef.current.token, false),
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`连接失败：${await extractErrorMessage(response)}`);
    }
    if (!response.body || !response.body.getReader) {
      throw new Error("当前浏览器暂不支持连续更新");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let reachedTerminal = false;
    let firstEventWatchdog: number | null = window.setTimeout(() => {
      const task = tasksRef.current[taskId];
      if (controller.signal.aborted || (task && TERMINAL_STATUSES.has(task.status))) {
        return;
      }
      upsertTask(taskId, {
        transport: "polling",
        note: "正在生成中。",
      });
      startPolling(taskId);
    }, 2500);

    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) {
          break;
        }
        buffer += decoder.decode(chunk.value, { stream: true });
        const parts = buffer.replace(/\r/g, "").split("\n\n");
        buffer = parts.pop() || "";
        for (const rawBlock of parts) {
          const payload = parseSseEvent(rawBlock);
          if (!payload) {
            continue;
          }
          if (firstEventWatchdog != null) {
            window.clearTimeout(firstEventWatchdog);
            firstEventWatchdog = null;
          }
          await applyEventPayload(taskId, payload, "sse");
          if (TERMINAL_STATUSES.has(payload.status as TaskStatus)) {
            reachedTerminal = true;
          }
        }
      }

      const tail = parseSseEvent(buffer.replace(/\r/g, ""));
      if (tail) {
        if (firstEventWatchdog != null) {
          window.clearTimeout(firstEventWatchdog);
          firstEventWatchdog = null;
        }
        await applyEventPayload(taskId, tail, "sse");
        if (TERMINAL_STATUSES.has(tail.status as TaskStatus)) {
          reachedTerminal = true;
        }
      }
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      throw error;
    } finally {
      try {
        reader.releaseLock();
      } catch {
        // ignore release errors
      }
      if (firstEventWatchdog != null) {
        window.clearTimeout(firstEventWatchdog);
      }
    }

    const currentTask = tasksRef.current[taskId];
    if (reachedTerminal || (currentTask && TERMINAL_STATUSES.has(currentTask.status))) {
      await fetchTask(configRef.current, taskId)
        .then((payload) => applyTaskSnapshot(taskId, payload, "snapshot"))
        .catch((error) => {
          console.warn("terminal refresh failed", error);
        });
      upsertTask(taskId, {
        transport: "complete",
        note: tasksRef.current[taskId]?.note || "模型已生成。",
      });
      stopSubscription(taskId);
      return;
    }
    throw new Error("连接已中断，请稍后刷新");
  }, [applyEventPayload, applyTaskSnapshot, configRef, parseSseEvent, startPolling, stopSubscription, subscriptionsRef, tasksRef, upsertTask]);

  const subscribeToTask = useCallback(async (taskId: string, force = false) => {
    if (!configRef.current.baseUrl) {
      throw new Error("请先填写服务地址");
    }
    if (!configRef.current.token) {
      throw new Error("请先填写 API 密钥");
    }
    if (!force && subscriptionsRef.current.has(taskId)) {
      return;
    }
    stopSubscription(taskId);
    upsertTask(taskId, {
      transport: "connecting",
      note: "正在准备中。",
    });

    try {
      await refreshTaskAction(taskId, { silent: true });
    } catch (error) {
      console.warn("initial task refresh failed before SSE", error);
    }

    try {
      await connectSse(taskId);
    } catch (error) {
      console.warn("falling back to polling", error);
      upsertTask(taskId, {
        transport: "polling",
        note: "正在生成中。",
      });
      startPolling(taskId);
    }
  }, [configRef, connectSse, refreshTaskAction, startPolling, stopSubscription, subscriptionsRef, upsertTask]);

  return {
    parseSseEvent,
    startPolling,
    connectSse,
    subscribeToTask,
  };
}
