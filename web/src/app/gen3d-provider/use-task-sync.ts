import {
  useCallback,
  useEffect,
  useRef,
  type MutableRefObject,
} from "react";
import { toast } from "sonner";

import { fetchTask } from "@/lib/api";
import {
  TERMINAL_STATUSES,
  defaultProgressForStatus,
  formatTaskStatus,
} from "@/lib/format";
import type {
  ApiConfig,
  GenerateState,
  TaskEventRecord,
  TaskRecord,
  TaskSnapshotPayload,
  TaskStatus,
  TaskSummaryPayload,
} from "@/lib/types";

import {
  buildLocalArtifactCandidates,
  isActiveStatus,
  normalizeTaskRecord,
  probeUrl,
  resolveArtifactUrl,
} from "./task-record-utils";

export function useTaskSync({
  configRef,
  tasksRef,
  generateRef,
  autoSelectionLockedRef,
  updateTasks,
  upsertTask,
  setCurrentTaskId,
  stopSubscription,
  syncCurrentTaskSelection,
}: {
  configRef: MutableRefObject<ApiConfig>;
  tasksRef: MutableRefObject<Record<string, TaskRecord>>;
  generateRef: MutableRefObject<GenerateState>;
  autoSelectionLockedRef: MutableRefObject<boolean>;
  updateTasks: (updater: (previous: Record<string, TaskRecord>) => Record<string, TaskRecord>) => void;
  upsertTask: (taskId: string, patch: Record<string, unknown>) => TaskRecord;
  setCurrentTaskId: (taskId: string) => void;
  stopSubscription: (taskId: string) => void;
  syncCurrentTaskSelection: (nextTasks: Record<string, TaskRecord>) => void;
}) {
  const applyTaskSnapshotRef = useRef<(taskId: string, payload: TaskSnapshotPayload, source: string) => Promise<void>>(async () => undefined);

  const hydrateArtifact = useCallback(async (task: TaskRecord) => {
    if (task.status !== "succeeded" || !Array.isArray(task.artifacts) || task.artifacts.length === 0) {
      upsertTask(task.taskId, {
        resolvedArtifactUrl: "",
        rawArtifactUrl: task.rawArtifactUrl || "",
      });
      return;
    }

    const glb = task.artifacts.find((artifact) => artifact.type === "glb") || task.artifacts[0];
    if (!glb || !glb.url) {
      upsertTask(task.taskId, {
        resolvedArtifactUrl: "",
        note: "模型已生成。",
      });
      return;
    }

    const rawArtifactUrl = String(glb.url || "").trim();
    const browserArtifactUrl = resolveArtifactUrl(rawArtifactUrl, configRef.current.baseUrl);

    if (/^https?:\/\//i.test(browserArtifactUrl)) {
      upsertTask(task.taskId, {
        resolvedArtifactUrl: browserArtifactUrl,
        rawArtifactUrl,
        note: rawArtifactUrl.startsWith("/")
          ? "模型已生成。"
          : glb.expires_at
            ? "模型已生成。"
            : task.note || "",
      });
      return;
    }

    if (!/^file:\/\//i.test(rawArtifactUrl)) {
      upsertTask(task.taskId, {
        resolvedArtifactUrl: browserArtifactUrl,
        rawArtifactUrl,
        note: "模型已生成。",
      });
      return;
    }

    const candidates = buildLocalArtifactCandidates(task.taskId, rawArtifactUrl, configRef.current.baseUrl);
    for (const candidate of candidates) {
      const ok = await probeUrl(candidate);
      if (ok) {
        upsertTask(task.taskId, {
          resolvedArtifactUrl: candidate,
          rawArtifactUrl,
          note: "模型已生成。",
        });
        return;
      }
    }

    upsertTask(task.taskId, {
      resolvedArtifactUrl: rawArtifactUrl,
      rawArtifactUrl,
      note: "模型已生成。",
    });
  }, [configRef, upsertTask]);

  const appendTaskEvent = useCallback((taskId: string, payload: Record<string, unknown>, source: string) => {
    updateTasks((previous) => {
      const task = previous[taskId];
      if (!task) {
        return previous;
      }
      const metadata = payload.metadata && typeof payload.metadata === "object"
        ? payload.metadata as Record<string, unknown>
        : null;
      const nextProgress = Number(payload.progress);
      const eventEntry: TaskEventRecord = {
        event: String(payload.event || payload.status || source),
        status: String(payload.status || task.status),
        progress: Number.isFinite(nextProgress) ? nextProgress : task.progress,
        currentStage: String(payload.currentStage || payload.current_stage || task.currentStage),
        timestamp: new Date().toISOString(),
        source,
        message: String(payload.message || metadata?.message || ""),
      };
      const previousEvent = task.events[task.events.length - 1];
      if (
        previousEvent
        && previousEvent.event === eventEntry.event
        && previousEvent.status === eventEntry.status
        && previousEvent.progress === eventEntry.progress
        && previousEvent.currentStage === eventEntry.currentStage
        && previousEvent.message === eventEntry.message
      ) {
        return previous;
      }
      return {
        ...previous,
        [taskId]: normalizeTaskRecord({
          ...task,
          events: [...task.events, eventEntry].slice(-30),
        }),
      };
    });
  }, [updateTasks]);

  const applyTaskSnapshot = useCallback(async (taskId: string, payload: TaskSnapshotPayload, source: string) => {
    const previous = tasksRef.current[taskId];
    const status = String(payload.status || previous?.status || "submitted") as TaskStatus;
    const task = upsertTask(taskId, {
      model: payload.model || previous?.model || "trellis",
      inputUrl: payload.inputUrl || payload.input_url || previous?.inputUrl || "",
      status,
      statusLabel: formatTaskStatus(status),
      progress: Number.isFinite(payload.progress) ? Number(payload.progress) : defaultProgressForStatus(status),
      currentStage: payload.currentStage || payload.current_stage || status,
      queuePosition: payload.queuePosition ?? payload.queue_position ?? null,
      estimatedWaitSeconds: payload.estimatedWaitSeconds ?? payload.estimated_wait_seconds ?? null,
      estimatedFinishAt: payload.estimatedFinishAt || payload.estimated_finish_at || null,
      createdAt: payload.createdAt || payload.created_at || previous?.createdAt || new Date().toISOString(),
      updatedAt: payload.updatedAt || payload.updated_at || new Date().toISOString(),
      lastSeenAt: new Date().toISOString(),
      error: payload.error || null,
      artifacts: Array.isArray(payload.artifacts) ? payload.artifacts : previous?.artifacts || [],
      rawArtifactUrl: Array.isArray(payload.artifacts) && payload.artifacts.length > 0
        ? String(payload.artifacts.find((artifact) => artifact.type === "glb")?.url || payload.artifacts[0]?.url || "")
        : previous?.rawArtifactUrl || "",
      transport: source === "sse" ? "sse" : source === "polling" ? "polling" : previous?.transport || "idle",
    });

    appendTaskEvent(taskId, payload as Record<string, unknown>, source);
    await hydrateArtifact(task);
    const hydratedTask = tasksRef.current[taskId] || task;

    if (hydratedTask.status === "succeeded" && !hydratedTask.resolvedArtifactUrl && !hydratedTask.successRefreshScheduled) {
      upsertTask(taskId, {
        successRefreshScheduled: true,
        note: hydratedTask.note || "模型已生成。",
      });
      fetchTask(configRef.current, taskId)
        .then((response) => applyTaskSnapshotRef.current(taskId, response, "snapshot"))
        .catch((error) => {
          console.warn("post-success refresh failed", error);
        })
        .finally(() => {
          if (tasksRef.current[taskId]) {
            upsertTask(taskId, { successRefreshScheduled: false });
          }
        });
    }

    if (TERMINAL_STATUSES.has(hydratedTask.status)) {
      stopSubscription(taskId);
    }
    const shouldAutoSelectActiveTask = isActiveStatus(hydratedTask.status)
      && !generateRef.current.currentTaskId
      && !autoSelectionLockedRef.current;
    if (generateRef.current.currentTaskId === taskId || shouldAutoSelectActiveTask) {
      setCurrentTaskId(taskId);
    }
  }, [appendTaskEvent, autoSelectionLockedRef, configRef, generateRef, hydrateArtifact, setCurrentTaskId, stopSubscription, tasksRef, upsertTask]);

  useEffect(() => {
    applyTaskSnapshotRef.current = applyTaskSnapshot;
  }, [applyTaskSnapshot]);

  const applyEventPayload = useCallback(async (taskId: string, payload: Record<string, unknown>, source: string) => {
    const metadata = payload.metadata && typeof payload.metadata === "object"
      ? payload.metadata as Record<string, unknown>
      : {};
    const nextStatus = typeof payload.status === "string" ? payload.status as TaskStatus : undefined;
    const nextProgress = Number(payload.progress);
    const nextStage = typeof payload.currentStage === "string" ? payload.currentStage : undefined;
    const metadataArtifacts = Array.isArray(metadata.artifacts)
      ? metadata.artifacts as TaskSnapshotPayload["artifacts"]
      : tasksRef.current[taskId]?.artifacts || [];
    await applyTaskSnapshot(taskId, {
      status: nextStatus,
      progress: Number.isFinite(nextProgress) ? nextProgress : undefined,
      currentStage: nextStage,
      updatedAt: new Date().toISOString(),
      error: metadata.error || metadata.failed_stage || metadata.message
        ? {
            message: String(metadata.message || metadata.error || ""),
            failed_stage: metadata.failed_stage || metadata.stage
              ? String(metadata.failed_stage || metadata.stage)
              : null,
          }
        : tasksRef.current[taskId]?.error || null,
      artifacts: metadataArtifacts,
    }, source);
  }, [applyTaskSnapshot, tasksRef]);

  const replaceTasksFromServer = useCallback(async (taskSummaries: TaskSummaryPayload[], append = false) => {
    const nextTasks = append ? { ...tasksRef.current } : {};
    taskSummaries.forEach((summary) => {
      const taskId = String(summary.taskId || summary.task_id || "").trim();
      if (!taskId) {
        return;
      }
      const current = tasksRef.current[taskId];
      nextTasks[taskId] = normalizeTaskRecord({
        ...(current || {}),
        taskId,
        model: summary.model || current?.model || "trellis",
        inputUrl: summary.inputUrl || summary.input_url || current?.inputUrl || "",
        createdAt: summary.createdAt || summary.created_at || current?.createdAt,
        updatedAt: summary.finishedAt || summary.finished_at || current?.updatedAt || current?.lastSeenAt,
        lastSeenAt: new Date().toISOString(),
        status: String(summary.status || current?.status || "submitted") as TaskStatus,
        statusLabel: formatTaskStatus(String(summary.status || current?.status || "submitted")),
        currentStage: current?.currentStage || String(summary.status || current?.status || "submitted"),
        progress: current?.progress ?? defaultProgressForStatus(String(summary.status || "submitted")),
        artifacts: summary.artifactUrl || summary.artifact_url
          ? [{ type: "glb", url: summary.artifactUrl || summary.artifact_url }]
          : current?.artifacts || [],
        rawArtifactUrl: summary.artifactUrl || summary.artifact_url || current?.rawArtifactUrl || "",
        transport: TERMINAL_STATUSES.has((summary.status || "") as TaskStatus)
          ? "complete"
          : current?.transport || "idle",
        resolvedArtifactUrl: current?.resolvedArtifactUrl || "",
        previewDataUrl: current?.previewDataUrl || "",
        note: current?.note || "",
      });
    });

    if (!append) {
      Array.from(Object.keys(tasksRef.current)).forEach((taskId) => {
        if (!nextTasks[taskId]) {
          stopSubscription(taskId);
        }
      });
    }

    updateTasks(() => nextTasks);
    await Promise.all(Object.values(nextTasks).map((task) => hydrateArtifact(task)));
    syncCurrentTaskSelection(nextTasks);
  }, [hydrateArtifact, stopSubscription, syncCurrentTaskSelection, tasksRef, updateTasks]);

  const refreshTaskAction = useCallback(async (taskId: string, { silent = true } = {}) => {
    const payload = await fetchTask(configRef.current, taskId) as TaskSnapshotPayload;
    await applyTaskSnapshot(taskId, payload, "snapshot");
    if (!silent) {
      toast.success("已刷新", {
        description: "内容已更新。",
      });
    }
  }, [applyTaskSnapshot, configRef]);

  return {
    hydrateArtifact,
    applyTaskSnapshot,
    applyEventPayload,
    replaceTasksFromServer,
    refreshTaskAction,
  };
}
