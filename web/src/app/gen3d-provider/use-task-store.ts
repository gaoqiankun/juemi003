import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { compareTaskRecords } from "@/lib/format";
import type {
  GalleryFilter,
  GenerateState,
  GenerateView,
  TaskPageState,
  TaskRecord,
} from "@/lib/types";

import {
  STORAGE_KEYS,
  TASK_PAGE_LIMIT,
  defaultGenerateState,
  readStoredConfig,
  readStoredCurrentTaskId,
} from "./state-persistence";
import { isActiveStatus, normalizeTaskRecord } from "./task-record-utils";

export interface SubscriptionHandle {
  mode: "sse" | "polling";
  controller?: AbortController;
  timer?: number;
}

export function useTaskStore() {
  const [tasks, setTasks] = useState<Record<string, TaskRecord>>({});
  const [taskPage, setTaskPage] = useState<TaskPageState>({
    limit: TASK_PAGE_LIMIT,
    nextCursor: "",
    hasMore: false,
    isLoading: false,
  });
  const [galleryFilter, setGalleryFilter] = useState<GalleryFilter>("all");
  const [generate, setGenerate] = useState<GenerateState>(() => {
    const config = readStoredConfig();
    return defaultGenerateState(config.token, readStoredCurrentTaskId());
  });

  const tasksRef = useRef(tasks);
  const taskPageRef = useRef(taskPage);
  const generateRef = useRef(generate);
  const autoSelectionLockedRef = useRef(false);
  const subscriptionsRef = useRef<Map<string, SubscriptionHandle>>(new Map());

  useEffect(() => {
    tasksRef.current = tasks;
  }, [tasks]);

  useEffect(() => {
    taskPageRef.current = taskPage;
  }, [taskPage]);

  useEffect(() => {
    generateRef.current = generate;
    try {
      if (generate.currentTaskId) {
        sessionStorage.setItem(STORAGE_KEYS.currentTask, generate.currentTaskId);
      } else {
        sessionStorage.removeItem(STORAGE_KEYS.currentTask);
      }
    } catch {
      // ignore private mode storage errors
    }
  }, [generate]);

  const updateTasks = useCallback((updater: (previous: Record<string, TaskRecord>) => Record<string, TaskRecord>) => {
    setTasks((previous) => {
      const next = updater(previous);
      tasksRef.current = next;
      return next;
    });
  }, []);

  const updateTaskPage = useCallback((updater: (previous: TaskPageState) => TaskPageState) => {
    setTaskPage((previous) => {
      const next = updater(previous);
      taskPageRef.current = next;
      return next;
    });
  }, []);

  const setCurrentTaskId = useCallback((taskId: string) => {
    if (taskId) {
      autoSelectionLockedRef.current = false;
    }
    setGenerate((previous) => ({
      ...previous,
      currentTaskId: taskId,
    }));
  }, []);

  const clearCurrentTaskSelection = useCallback(({ lockAutoSync = false }: { lockAutoSync?: boolean } = {}) => {
    if (lockAutoSync) {
      autoSelectionLockedRef.current = true;
    }
    setGenerate((previous) => ({
      ...previous,
      currentTaskId: "",
    }));
  }, []);

  const upsertTask = useCallback((taskId: string, patch: Record<string, unknown>) => {
    let nextTask: TaskRecord | null = null;
    updateTasks((previous) => {
      const merged = normalizeTaskRecord({
        ...(previous[taskId] || { taskId }),
        ...patch,
        taskId,
      });
      nextTask = merged;
      return {
        ...previous,
        [taskId]: merged,
      };
    });
    return nextTask ?? normalizeTaskRecord({ taskId });
  }, [updateTasks]);

  const stopSubscription = useCallback((taskId: string) => {
    const current = subscriptionsRef.current.get(taskId);
    if (!current) {
      return;
    }
    if (current.mode === "sse") {
      current.controller?.abort();
    }
    if (current.mode === "polling" && typeof current.timer === "number") {
      window.clearInterval(current.timer);
    }
    subscriptionsRef.current.delete(taskId);
  }, []);

  const removeTask = useCallback((taskId: string, configToken = "") => {
    stopSubscription(taskId);
    updateTasks((previous) => {
      if (!previous[taskId]) {
        return previous;
      }
      const next = { ...previous };
      delete next[taskId];
      return next;
    });
    if (generateRef.current.currentTaskId === taskId) {
      setGenerate((previous) => ({
        ...defaultGenerateState(configToken, ""),
        callbackUrl: previous.callbackUrl,
      }));
    }
  }, [stopSubscription, updateTasks]);

  const resetTaskState = useCallback(() => {
    Array.from(subscriptionsRef.current.keys()).forEach((taskId) => stopSubscription(taskId));
    updateTasks(() => ({}));
    updateTaskPage(() => ({
      limit: TASK_PAGE_LIMIT,
      nextCursor: "",
      hasMore: false,
      isLoading: false,
    }));
    autoSelectionLockedRef.current = false;
    clearCurrentTaskSelection();
  }, [clearCurrentTaskSelection, stopSubscription, updateTaskPage, updateTasks]);

  const syncCurrentTaskSelection = useCallback((nextTasks: Record<string, TaskRecord>) => {
    const currentTaskId = generateRef.current.currentTaskId;
    if (currentTaskId && nextTasks[currentTaskId]) {
      return;
    }
    if (autoSelectionLockedRef.current) {
      if (currentTaskId && !nextTasks[currentTaskId]) {
        clearCurrentTaskSelection();
      }
      return;
    }
    const latestActive = Object.values(nextTasks)
      .filter((task) => isActiveStatus(task.status))
      .sort(compareTaskRecords)[0];
    if (latestActive) {
      setCurrentTaskId(latestActive.taskId);
      return;
    }
    if (currentTaskId && !nextTasks[currentTaskId]) {
      clearCurrentTaskSelection();
    }
  }, [clearCurrentTaskSelection, setCurrentTaskId]);

  useEffect(() => {
    const activeSubscriptions = subscriptionsRef.current;
    return () => {
      Array.from(activeSubscriptions.keys()).forEach((taskId) => stopSubscription(taskId));
    };
  }, [stopSubscription]);

  const sortedTasks = useMemo(() => Object.values(tasks).sort(compareTaskRecords), [tasks]);
  const currentTask = useMemo(() => (generate.currentTaskId ? tasks[generate.currentTaskId] || null : null), [generate.currentTaskId, tasks]);
  const generateView = useMemo<GenerateView>(() => {
    if (generate.isUploading || generate.isSubmitting) {
      return "uploading";
    }
    if (!currentTask) {
      return "idle";
    }
    if (currentTask.status === "succeeded") {
      return "completed";
    }
    if (currentTask.status === "failed" || currentTask.status === "cancelled") {
      return "failed";
    }
    return "processing";
  }, [currentTask, generate.isSubmitting, generate.isUploading]);

  const getFilteredTasks = useCallback((filter: GalleryFilter = galleryFilter) => {
    if (filter === "processing") {
      return sortedTasks.filter((task) => isActiveStatus(task.status));
    }
    if (filter === "completed") {
      return sortedTasks.filter((task) => task.status === "succeeded");
    }
    if (filter === "failed") {
      return sortedTasks.filter((task) => task.status === "failed" || task.status === "cancelled");
    }
    return sortedTasks;
  }, [galleryFilter, sortedTasks]);

  return {
    tasks,
    taskMap: tasks,
    taskPage,
    galleryFilter,
    setGalleryFilter,
    generate,
    sortedTasks,
    currentTask,
    generateView,
    getFilteredTasks,
    setGenerate,
    tasksRef,
    taskPageRef,
    generateRef,
    autoSelectionLockedRef,
    subscriptionsRef,
    updateTasks,
    updateTaskPage,
    setCurrentTaskId,
    clearCurrentTaskSelection,
    upsertTask,
    stopSubscription,
    removeTask,
    resetTaskState,
    syncCurrentTaskSelection,
  };
}
