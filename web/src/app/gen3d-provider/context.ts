import { createContext, useContext } from "react";

import { CANCELLABLE_STATUSES } from "@/lib/format";
import type {
  ApiConfig,
  ConnectionState,
  GalleryFilter,
  GenerateState,
  GenerateView,
  HealthPayload,
  TaskPageState,
  TaskRecord,
  TaskStatus,
} from "@/lib/types";

export interface Gen3dContextValue {
  config: ApiConfig;
  connection: ConnectionState;
  tasks: TaskRecord[];
  taskMap: Record<string, TaskRecord>;
  taskPage: TaskPageState;
  generate: GenerateState;
  currentTask: TaskRecord | null;
  generateView: GenerateView;
  galleryFilter: GalleryFilter;
  setGalleryFilter: (filter: GalleryFilter) => void;
  getFilteredTasks: (filter?: GalleryFilter) => TaskRecord[];
  saveConfig: (next: Partial<ApiConfig>) => Promise<void>;
  pingHealth: (silent?: boolean) => Promise<HealthPayload>;
  refreshTaskList: (options?: { append?: boolean; resubscribe?: boolean; silent?: boolean }) => Promise<void>;
  refreshTask: (taskId: string, options?: { silent?: boolean }) => Promise<void>;
  selectFile: (file: File | null) => Promise<void>;
  clearSelectedFile: (keepStatus?: boolean) => void;
  submitCurrentFile: (modelId?: string) => Promise<string | undefined>;
  retryCurrentTask: (modelId?: string) => Promise<string | undefined>;
  cancelTask: (taskId: string) => Promise<void>;
  deleteTask: (taskId: string) => Promise<void>;
  subscribeToTask: (taskId: string, force?: boolean) => Promise<void>;
  setCurrentTaskId: (taskId: string) => void;
  clearCurrentTaskSelection: (options?: { lockAutoSync?: boolean }) => void;
}

export const Gen3dContext = createContext<Gen3dContextValue | null>(null);

export function useGen3d() {
  const context = useContext(Gen3dContext);
  if (!context) {
    throw new Error("useGen3d must be used within Gen3dProvider");
  }
  return context;
}

export function canCancelTask(task: TaskRecord | null | undefined) {
  return Boolean(task) && CANCELLABLE_STATUSES.has((task?.status || "") as TaskStatus) && !task?.pendingCancel;
}
