import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { normalizeBaseUrl } from "@/lib/api";
import type {
  ApiConfig,
  ConnectionState,
} from "@/lib/types";

import {
  Gen3dContext,
  canCancelTask,
  useGen3d,
  type Gen3dContextValue,
} from "./gen3d-provider/context";
import {
  STORAGE_KEYS,
  defaultConnectionState,
  readStoredConfig,
} from "./gen3d-provider/state-persistence";
import { useConfigBootstrap } from "./gen3d-provider/use-config-bootstrap";
import { useGenerateWorkflow } from "./gen3d-provider/use-generate-workflow";
import { useTaskRealtime } from "./gen3d-provider/use-task-realtime";
import { useTaskStore } from "./gen3d-provider/use-task-store";
import { useTaskSync } from "./gen3d-provider/use-task-sync";

export function Gen3dProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<ApiConfig>(() => readStoredConfig());
  const [connection, setConnection] = useState<ConnectionState>(defaultConnectionState);
  const configRef = useRef(config);

  useEffect(() => {
    configRef.current = config;
  }, [config]);

  const persistConfig = useCallback((next: Partial<ApiConfig>) => {
    setConfig((previous) => {
      const merged = {
        baseUrl: normalizeBaseUrl(next.baseUrl ?? previous.baseUrl),
        token: String(next.token ?? previous.token).trim(),
      };
      try {
        localStorage.setItem(STORAGE_KEYS.config, JSON.stringify(merged));
      } catch {
        // ignore storage failures
      }
      return merged;
    });
  }, []);

  const {
    taskMap,
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
  } = useTaskStore();

  const {
    applyTaskSnapshot,
    applyEventPayload,
    replaceTasksFromServer,
    refreshTaskAction,
  } = useTaskSync({
    configRef,
    tasksRef,
    generateRef,
    autoSelectionLockedRef,
    updateTasks,
    upsertTask,
    setCurrentTaskId,
    stopSubscription,
    syncCurrentTaskSelection,
  });

  const { subscribeToTask } = useTaskRealtime({
    configRef,
    tasksRef,
    subscriptionsRef,
    stopSubscription,
    upsertTask,
    refreshTaskAction,
    applyEventPayload,
    applyTaskSnapshot,
  });

  const {
    pingHealthAction,
    refreshTaskListAction,
    saveConfig,
  } = useConfigBootstrap({
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
  });

  const {
    clearSelectedFile,
    selectFile,
    submitCurrentFile,
    retryCurrentTask,
    cancelTask,
    deleteTask,
  } = useGenerateWorkflow({
    configRef,
    tasksRef,
    generateRef,
    autoSelectionLockedRef,
    setGenerate: (updater) => setGenerate(updater),
    upsertTask,
    setCurrentTaskId,
    clearCurrentTaskSelection,
    removeTask,
    refreshTaskListAction,
    subscribeToTask,
    applyTaskSnapshot,
  });

  const value = useMemo<Gen3dContextValue>(() => ({
    config,
    connection,
    tasks: sortedTasks,
    taskMap,
    taskPage,
    generate,
    currentTask,
    generateView,
    galleryFilter,
    setGalleryFilter,
    getFilteredTasks,
    saveConfig,
    pingHealth: pingHealthAction,
    refreshTaskList: refreshTaskListAction,
    refreshTask: refreshTaskAction,
    selectFile,
    clearSelectedFile,
    submitCurrentFile,
    retryCurrentTask,
    cancelTask,
    deleteTask,
    subscribeToTask,
    setCurrentTaskId,
    clearCurrentTaskSelection,
  }), [
    cancelTask,
    clearCurrentTaskSelection,
    clearSelectedFile,
    config,
    connection,
    currentTask,
    deleteTask,
    galleryFilter,
    generate,
    generateView,
    getFilteredTasks,
    pingHealthAction,
    refreshTaskAction,
    refreshTaskListAction,
    retryCurrentTask,
    saveConfig,
    selectFile,
    setCurrentTaskId,
    setGalleryFilter,
    sortedTasks,
    subscribeToTask,
    submitCurrentFile,
    taskMap,
    taskPage,
  ]);

  return <Gen3dContext.Provider value={value}>{children}</Gen3dContext.Provider>;
}

export {
  Gen3dContext,
  canCancelTask,
  useGen3d,
};

export type { Gen3dContextValue };
