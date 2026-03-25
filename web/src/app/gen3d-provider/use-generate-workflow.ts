import { useCallback, type MutableRefObject } from "react";
import { toast } from "sonner";

import {
  createTask,
  requestTaskCancel,
  requestTaskDelete,
  uploadFile,
} from "@/lib/api";
import {
  TERMINAL_STATUSES,
  defaultProgressForStatus,
  formatTaskStatus,
} from "@/lib/format";
import { readFileAsDataUrl } from "@/lib/utils";
import type {
  ApiConfig,
  GenerateState,
  TaskCreatePayload,
  TaskRecord,
  TaskSnapshotPayload,
} from "@/lib/types";

export function useGenerateWorkflow({
  configRef,
  tasksRef,
  generateRef,
  autoSelectionLockedRef,
  setGenerate,
  upsertTask,
  setCurrentTaskId,
  clearCurrentTaskSelection,
  removeTask,
  refreshTaskListAction,
  subscribeToTask,
  applyTaskSnapshot,
}: {
  configRef: MutableRefObject<ApiConfig>;
  tasksRef: MutableRefObject<Record<string, TaskRecord>>;
  generateRef: MutableRefObject<GenerateState>;
  autoSelectionLockedRef: MutableRefObject<boolean>;
  setGenerate: (updater: (previous: GenerateState) => GenerateState) => void;
  upsertTask: (taskId: string, patch: Record<string, unknown>) => TaskRecord;
  setCurrentTaskId: (taskId: string) => void;
  clearCurrentTaskSelection: (options?: { lockAutoSync?: boolean }) => void;
  removeTask: (taskId: string, configToken?: string) => void;
  refreshTaskListAction: (options?: { append?: boolean; resubscribe?: boolean; silent?: boolean }) => Promise<void>;
  subscribeToTask: (taskId: string, force?: boolean) => Promise<void>;
  applyTaskSnapshot: (taskId: string, payload: TaskSnapshotPayload, source: string) => Promise<void>;
}) {
  const clearSelectedFile = useCallback((keepStatus = false) => {
    setGenerate((previous) => ({
      ...previous,
      file: null,
      previewDataUrl: "",
      uploadedUrl: "",
      uploadId: "",
      name: "",
      uploadProgress: 0,
      statusMessage: keepStatus
        ? previous.statusMessage
        : configRef.current.token
          ? "图片就绪后即可开始生成。"
          : "请先到设置页配置连接。",
      statusTone: keepStatus ? previous.statusTone : configRef.current.token ? "info" : "error",
    }));
  }, [configRef, setGenerate]);

  const selectFile = useCallback(async (file: File | null) => {
    if (!file) {
      clearSelectedFile(false);
      return;
    }
    const selectedTask = tasksRef.current[generateRef.current.currentTaskId];
    const shouldClearSelection = Boolean(selectedTask && TERMINAL_STATUSES.has(selectedTask.status));
    if (shouldClearSelection) {
      autoSelectionLockedRef.current = true;
    }
    const previewDataUrl = await readFileAsDataUrl(file);
    setGenerate((previous) => ({
      ...previous,
      file,
      previewDataUrl,
      uploadedUrl: "",
      uploadId: "",
      name: file.name,
      statusMessage: configRef.current.token
        ? "图片已准备；确认后会自动上传并开始生成。"
        : "图片预览已就绪；请先填写 API 密钥。",
      statusTone: configRef.current.token ? "info" : "error",
      currentTaskId: shouldClearSelection ? "" : previous.currentTaskId,
    }));
  }, [autoSelectionLockedRef, clearSelectedFile, configRef, generateRef, setGenerate, tasksRef]);

  const ensureUploadedInput = useCallback(async () => {
    if (!configRef.current.baseUrl) {
      throw new Error("请先填写服务地址");
    }
    if (!configRef.current.token) {
      throw new Error("请先填写 API 密钥");
    }
    if (!generateRef.current.file) {
      throw new Error("请先选择一张输入图片");
    }
    if (generateRef.current.uploadedUrl) {
      return generateRef.current.uploadedUrl;
    }
    setGenerate((previous) => ({
      ...previous,
      isUploading: true,
      uploadProgress: 0,
      statusMessage: "正在上传图片：0%",
      statusTone: "info",
    }));
    try {
      const result = await uploadFile(configRef.current, generateRef.current.file, (progress) => {
        setGenerate((previous) => ({
          ...previous,
          uploadProgress: progress,
          statusMessage: `正在上传图片：${progress}%`,
          statusTone: "info",
        }));
      });
      setGenerate((previous) => ({
        ...previous,
        uploadedUrl: result.url,
        uploadId: String(result.uploadId || result.upload_id || ""),
        statusMessage: "上传完成，正在开始生成…",
        statusTone: "success",
      }));
      return result.url;
    } finally {
      setGenerate((previous) => ({
        ...previous,
        isUploading: false,
      }));
    }
  }, [configRef, generateRef, setGenerate]);

  const submitNewTask = useCallback(async (inputUrl: string, modelId: string, previewDataUrl?: string) => {
    const callbackUrl = String(generateRef.current.callbackUrl || "").trim();
    const payload: TaskCreatePayload = {
      type: "image_to_3d",
      image_url: inputUrl,
      model: modelId,
    };
    if (callbackUrl) {
      payload.callback_url = callbackUrl;
    }

    setGenerate((previous) => ({
      ...previous,
      isSubmitting: true,
      uploadProgress: 0,
      statusMessage: "正在开始生成…",
      statusTone: "info",
    }));

    try {
      const result = await createTask(configRef.current, payload);
      const taskId = String(result.taskId || result.task_id || "");
      setCurrentTaskId(taskId);
      upsertTask(taskId, {
        status: String(result.status || "submitted"),
        statusLabel: formatTaskStatus(String(result.status || "submitted")),
        currentStage: String(result.status || "submitted"),
        progress: defaultProgressForStatus(String(result.status || "submitted")),
        queuePosition: result.queuePosition ?? result.queue_position ?? null,
        estimatedWaitSeconds: result.estimatedWaitSeconds ?? result.estimated_wait_seconds ?? null,
        estimatedFinishAt: result.estimatedFinishAt || result.estimated_finish_at || null,
        model: result.model || "trellis",
        inputUrl: result.inputUrl || result.input_url || inputUrl,
        createdAt: new Date().toISOString(),
        submittedAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        lastSeenAt: new Date().toISOString(),
        transport: "connecting",
        note: "正在生成中。",
        previewDataUrl: previewDataUrl || generateRef.current.previewDataUrl,
        artifacts: [],
        events: [],
      });
      await refreshTaskListAction({ append: false, resubscribe: false, silent: true }).catch((error) => {
        console.warn("silent list refresh failed after submit", error);
      });
      subscribeToTask(taskId, true).catch((error) => {
        console.warn("background subscription failed after submit", error);
        toast.error("连接失败", {
          description: error instanceof Error ? error.message : String(error),
        });
      });
      toast.success("已开始生成", {
        description: "模型正在生成中。",
      });
      return taskId;
    } finally {
      setGenerate((previous) => ({
        ...previous,
        isSubmitting: false,
      }));
    }
  }, [configRef, generateRef, refreshTaskListAction, setCurrentTaskId, setGenerate, subscribeToTask, upsertTask]);

  const submitCurrentFile = useCallback(async (modelId?: string) => {
    if (generateRef.current.isUploading || generateRef.current.isSubmitting) {
      return undefined;
    }
    const normalizedModelId = String(modelId || "").trim();
    if (!normalizedModelId) {
      throw new Error("请先选择一个生成模型。");
    }
    const inputUrl = await ensureUploadedInput();
    return submitNewTask(inputUrl, normalizedModelId, generateRef.current.previewDataUrl);
  }, [ensureUploadedInput, generateRef, submitNewTask]);

  const retryCurrentTask = useCallback(async (modelId?: string) => {
    const currentTask = tasksRef.current[generateRef.current.currentTaskId];
    if (!currentTask?.inputUrl) {
      throw new Error("当前记录缺少原图，请重新上传图片。");
    }
    const normalizedModelId = String(modelId || currentTask.model || "").trim();
    if (!normalizedModelId) {
      throw new Error("请先选择一个生成模型。");
    }
    if (TERMINAL_STATUSES.has(currentTask.status)) {
      clearCurrentTaskSelection({ lockAutoSync: true });
    }
    return submitNewTask(
      currentTask.inputUrl,
      normalizedModelId,
      currentTask.previewDataUrl || generateRef.current.previewDataUrl,
    );
  }, [clearCurrentTaskSelection, generateRef, submitNewTask, tasksRef]);

  const cancelTask = useCallback(async (taskId: string) => {
    upsertTask(taskId, { pendingCancel: true });
    try {
      const payload = await requestTaskCancel(configRef.current, taskId);
      await applyTaskSnapshot(taskId, payload, "snapshot");
      toast.success("已取消", {
        description: "本次生成已取消。",
      });
    } finally {
      if (tasksRef.current[taskId]) {
        upsertTask(taskId, { pendingCancel: false });
      }
    }
  }, [applyTaskSnapshot, configRef, tasksRef, upsertTask]);

  const deleteTask = useCallback(async (taskId: string) => {
    upsertTask(taskId, { pendingDelete: true });
    try {
      await requestTaskDelete(configRef.current, taskId);
      removeTask(taskId, configRef.current.token);
      toast.success("已删除", {
        description: "这条记录已从图库中移除。",
      });
    } finally {
      if (tasksRef.current[taskId]) {
        upsertTask(taskId, { pendingDelete: false });
      }
    }
  }, [configRef, removeTask, tasksRef, upsertTask]);

  return {
    clearSelectedFile,
    selectFile,
    submitCurrentFile,
    retryCurrentTask,
    cancelTask,
    deleteTask,
  };
}
