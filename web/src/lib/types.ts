export type TaskStatus =
  | "submitted"
  | "queued"
  | "preprocessing"
  | "gpu_queued"
  | "gpu_ss"
  | "gpu_shape"
  | "gpu_material"
  | "exporting"
  | "uploading"
  | "succeeded"
  | "failed"
  | "cancelled";

export type ConnectionTone = "ready" | "error" | "empty";
export type StatusTone = "info" | "success" | "error";
export type GenerateView = "idle" | "uploading" | "processing" | "completed" | "failed";
export type GalleryFilter = "all" | "processing" | "completed" | "failed";

export interface ApiConfig {
  baseUrl: string;
  token: string;
}

export interface ConnectionState {
  tone: ConnectionTone;
  label: string;
  detail: string;
}

export interface ArtifactPayload {
  type: string;
  url?: string | null;
  created_at?: string | null;
  size_bytes?: number | null;
  backend?: string | null;
  content_type?: string | null;
  expires_at?: string | null;
}

export interface TaskErrorPayload {
  message: string;
  failed_stage?: string | null;
}

export interface TaskRecord {
  taskId: string;
  model: string;
  inputUrl: string;
  createdAt: string;
  submittedAt: string;
  updatedAt: string;
  lastSeenAt: string;
  status: TaskStatus;
  statusLabel: string;
  progress: number;
  currentStage: string;
  queuePosition: number | null;
  estimatedWaitSeconds: number | null;
  estimatedFinishAt: string | null;
  artifacts: ArtifactPayload[];
  error: TaskErrorPayload | null;
  events: TaskEventRecord[];
  transport: string;
  note: string;
  resolvedArtifactUrl: string;
  rawArtifactUrl: string;
  previewDataUrl: string;
  thumbnailUrl: string;
  thumbnailState: "idle" | "loading" | "ready" | "failed";
  pendingDelete: boolean;
  pendingCancel: boolean;
  successRefreshScheduled: boolean;
}

export interface TaskEventRecord {
  event: string;
  status: string;
  progress: number;
  currentStage: string;
  timestamp: string;
  source: string;
  message: string;
}

export interface TaskSummaryPayload {
  taskId?: string;
  task_id?: string;
  status?: TaskStatus;
  model?: string;
  inputUrl?: string;
  input_url?: string;
  createdAt?: string;
  created_at?: string;
  finishedAt?: string | null;
  finished_at?: string | null;
  artifactUrl?: string | null;
  artifact_url?: string | null;
}

export interface TaskSnapshotPayload {
  taskId?: string;
  task_id?: string;
  status?: TaskStatus;
  model?: string;
  inputUrl?: string;
  input_url?: string;
  progress?: number;
  currentStage?: string;
  current_stage?: string;
  queuePosition?: number | null;
  queue_position?: number | null;
  estimatedWaitSeconds?: number | null;
  estimated_wait_seconds?: number | null;
  estimatedFinishAt?: string | null;
  estimated_finish_at?: string | null;
  createdAt?: string;
  created_at?: string;
  updatedAt?: string;
  updated_at?: string;
  artifacts?: ArtifactPayload[];
  error?: TaskErrorPayload | null;
}

export interface TaskListPayload {
  items: TaskSummaryPayload[];
  hasMore?: boolean;
  has_more?: boolean;
  nextCursor?: string | null;
  next_cursor?: string | null;
}

export interface TaskCreatePayload {
  type: "image_to_3d";
  input_url?: string;
  image_url?: string;
  callback_url?: string;
  options?: {
    resolution?: 512 | 1024 | 1536;
  };
}

export interface UploadResponse {
  uploadId?: string;
  upload_id?: string;
  url: string;
}

export interface HealthPayload {
  status: "ok" | "ready" | "not_ready";
  service: string;
}

export interface GenerateState {
  file: File | null;
  previewDataUrl: string;
  uploadedUrl: string;
  uploadId: string;
  name: string;
  callbackUrl: string;
  isUploading: boolean;
  uploadProgress: number;
  isSubmitting: boolean;
  statusMessage: string;
  statusTone: StatusTone;
  currentTaskId: string;
}

export interface TaskPageState {
  limit: number;
  nextCursor: string;
  hasMore: boolean;
  isLoading: boolean;
}
