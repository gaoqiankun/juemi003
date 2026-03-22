export type AdminLocale = "en" | "zh-CN";
export type ThemeMode = "dark" | "light";

export type TaskStatus = "live" | "queued" | "completed" | "failed";
export type NodeStatus = "online" | "warning" | "offline";
export type ModelStatus = "ready" | "syncing" | "queued";
export type KeyStatus = "active" | "rotating" | "paused";

export type DashboardStatKey = "activeTasks" | "queued" | "completed" | "failed";

export interface DashboardStat {
  key: DashboardStatKey;
  value: number;
  change: string;
}

export interface RecentTask {
  id: string;
  subjectKey: string;
  model: string;
  status: TaskStatus;
  durationSeconds: number;
  createdAt: string;
  owner: string;
}

export interface InfrastructureNode {
  id: string;
  zone: string;
  gpu: string;
  status: NodeStatus;
  utilization: number;
  pendingTasks: number;
  uptimeHours: number;
  throughputPerHour: number;
}

export interface DashboardData {
  stats: DashboardStat[];
  gpu: {
    model: string;
    utilization: number;
    vramUsedGb: number;
    vramTotalGb: number;
    temperatureC: number;
    powerW: number;
    fanPercent: number;
    cudaVersion: string;
    driverVersion: string;
    activeJobs: number;
    avgLatencySeconds: number;
  };
  recentTasks: RecentTask[];
  nodes: InfrastructureNode[];
}

export interface TaskOverviewMetric {
  key: "throughput" | "latency" | "active";
  value: number;
  unit?: string;
  change: string;
}

export interface QueueTask {
  id: string;
  subjectKey: string;
  model: string;
  status: TaskStatus;
  progress: number;
  queue: string;
  createdAt: string;
  latencySeconds: number;
  owner: string;
}

export interface TaskLogEntry {
  timestamp: string;
  level: "info" | "warn" | "error";
  messageKey: string;
}

export interface TasksData {
  overview: TaskOverviewMetric[];
  tasks: QueueTask[];
  logs: TaskLogEntry[];
}

export interface ModelCardData {
  id: string;
  name: string;
  provider: string;
  version: string;
  status: ModelStatus;
  sizeGb: number;
  minVramGb: number;
  downloads: number;
  progress: number;
  capabilities: string[];
  updatedAt: string;
}

export interface ModelsData {
  models: ModelCardData[];
  summary: {
    ready: number;
    syncing: number;
    queued: number;
    storageUsedGb: number;
  };
}

export interface ApiUsageMetric {
  key: "requests" | "projects" | "spend" | "errorRate";
  value: number;
}

export interface ApiKeyData {
  id: string;
  name: string;
  prefix: string;
  createdAt: string;
  lastUsedAt: string;
  requests: number;
  scopes: string[];
  status: KeyStatus;
  owner: string;
}

export interface ApiKeysData {
  usage: ApiUsageMetric[];
  keys: ApiKeyData[];
}

export type SettingFieldType = "toggle" | "number" | "text" | "select";

export interface SettingOption {
  labelKey?: string;
  label?: string;
  value: string;
}

export interface SettingField {
  key: string;
  labelKey: string;
  descriptionKey: string;
  type: SettingFieldType;
  value: boolean | number | string;
  suffix?: string;
  suffixKey?: string;
  options?: SettingOption[];
}

export interface SettingSection {
  key: string;
  titleKey: string;
  descriptionKey: string;
  fields: SettingField[];
}

export interface SettingsData {
  sections: SettingSection[];
}

export const dashboardData: DashboardData = {
  stats: [
    { key: "activeTasks", value: 24, change: "+12%" },
    { key: "queued", value: 7, change: "-3%" },
    { key: "completed", value: 1382, change: "+18%" },
    { key: "failed", value: 14, change: "-0.6%" },
  ],
  gpu: {
    model: "NVIDIA RTX 6000 Ada",
    utilization: 87,
    vramUsedGb: 39.4,
    vramTotalGb: 48,
    temperatureC: 71,
    powerW: 287,
    fanPercent: 62,
    cudaVersion: "12.4",
    driverVersion: "550.54",
    activeJobs: 5,
    avgLatencySeconds: 184,
  },
  recentTasks: [
    {
      id: "tsk_6fe91b4c",
      subjectKey: "subjects.sneaker",
      model: "TRELLIS2 Large",
      status: "live",
      durationSeconds: 182,
      createdAt: "2026-03-20T14:12:00+08:00",
      owner: "studio-render",
    },
    {
      id: "tsk_7ca829ad",
      subjectKey: "subjects.chair",
      model: "HunYuan3D-2",
      status: "queued",
      durationSeconds: 0,
      createdAt: "2026-03-20T14:07:00+08:00",
      owner: "product-lab",
    },
    {
      id: "tsk_a41dbf12",
      subjectKey: "subjects.headphones",
      model: "TRELLIS2 Large",
      status: "completed",
      durationSeconds: 156,
      createdAt: "2026-03-20T13:58:00+08:00",
      owner: "brand-x",
    },
    {
      id: "tsk_bd1730a7",
      subjectKey: "subjects.drone",
      model: "HunYuan3D-2",
      status: "failed",
      durationSeconds: 48,
      createdAt: "2026-03-20T13:52:00+08:00",
      owner: "internal-rnd",
    },
    {
      id: "tsk_cc09d522",
      subjectKey: "subjects.lamp",
      model: "TRELLIS2 Lite",
      status: "completed",
      durationSeconds: 129,
      createdAt: "2026-03-20T13:39:00+08:00",
      owner: "milan-drop",
    },
  ],
  nodes: [
    {
      id: "cubie-gpu-01",
      zone: "cn-sha-a",
      gpu: "RTX 6000 Ada",
      status: "online",
      utilization: 91,
      pendingTasks: 3,
      uptimeHours: 428,
      throughputPerHour: 14.2,
    },
    {
      id: "cubie-gpu-02",
      zone: "cn-sha-a",
      gpu: "A6000",
      status: "online",
      utilization: 76,
      pendingTasks: 2,
      uptimeHours: 389,
      throughputPerHour: 11.4,
    },
    {
      id: "cubie-gpu-03",
      zone: "cn-sha-b",
      gpu: "RTX 4090",
      status: "warning",
      utilization: 54,
      pendingTasks: 5,
      uptimeHours: 132,
      throughputPerHour: 9.1,
    },
    {
      id: "cubie-edge-01",
      zone: "cn-hkg-a",
      gpu: "L40S",
      status: "offline",
      utilization: 0,
      pendingTasks: 0,
      uptimeHours: 0,
      throughputPerHour: 0,
    },
  ],
};

export const tasksData: TasksData = {
  overview: [
    { key: "throughput", value: 14.2, unit: "/h", change: "+1.8/h" },
    { key: "latency", value: 186, unit: "s", change: "-14s" },
    { key: "active", value: 24, change: "+4" },
  ],
  tasks: [
    {
      id: "tsk_6fe91b4c",
      subjectKey: "subjects.sneaker",
      model: "TRELLIS2 Large",
      status: "live",
      progress: 82,
      queue: "priority-render",
      createdAt: "2026-03-20T14:12:00+08:00",
      latencySeconds: 182,
      owner: "studio-render",
    },
    {
      id: "tsk_7ca829ad",
      subjectKey: "subjects.chair",
      model: "HunYuan3D-2",
      status: "queued",
      progress: 14,
      queue: "default",
      createdAt: "2026-03-20T14:07:00+08:00",
      latencySeconds: 0,
      owner: "product-lab",
    },
    {
      id: "tsk_72db1281",
      subjectKey: "subjects.camera",
      model: "TRELLIS2 Lite",
      status: "live",
      progress: 58,
      queue: "bulk-sync",
      createdAt: "2026-03-20T13:59:00+08:00",
      latencySeconds: 144,
      owner: "agency-ops",
    },
    {
      id: "tsk_a41dbf12",
      subjectKey: "subjects.headphones",
      model: "TRELLIS2 Large",
      status: "completed",
      progress: 100,
      queue: "priority-render",
      createdAt: "2026-03-20T13:58:00+08:00",
      latencySeconds: 156,
      owner: "brand-x",
    },
    {
      id: "tsk_20ed0f48",
      subjectKey: "subjects.watch",
      model: "HunYuan3D-2",
      status: "completed",
      progress: 100,
      queue: "default",
      createdAt: "2026-03-20T13:47:00+08:00",
      latencySeconds: 201,
      owner: "merch-lab",
    },
    {
      id: "tsk_bd1730a7",
      subjectKey: "subjects.drone",
      model: "HunYuan3D-2",
      status: "failed",
      progress: 36,
      queue: "experiments",
      createdAt: "2026-03-20T13:52:00+08:00",
      latencySeconds: 48,
      owner: "internal-rnd",
    },
    {
      id: "tsk_cc09d522",
      subjectKey: "subjects.lamp",
      model: "TRELLIS2 Lite",
      status: "completed",
      progress: 100,
      queue: "default",
      createdAt: "2026-03-20T13:39:00+08:00",
      latencySeconds: 129,
      owner: "milan-drop",
    },
    {
      id: "tsk_10fc31d0",
      subjectKey: "subjects.jacket",
      model: "TRELLIS2 Large",
      status: "queued",
      progress: 4,
      queue: "priority-render",
      createdAt: "2026-03-20T13:35:00+08:00",
      latencySeconds: 0,
      owner: "fashion-rnd",
    },
  ],
  logs: [
    { timestamp: "14:12:18", level: "info", messageKey: "tasks.logs.allocateGpu" },
    { timestamp: "14:11:57", level: "info", messageKey: "tasks.logs.materialStage" },
    { timestamp: "14:11:42", level: "warn", messageKey: "tasks.logs.queueDepth" },
    { timestamp: "14:10:15", level: "info", messageKey: "tasks.logs.previewReady" },
    { timestamp: "14:09:44", level: "error", messageKey: "tasks.logs.edgeNode" },
    { timestamp: "14:08:03", level: "info", messageKey: "tasks.logs.downloadCache" },
  ],
};

export const modelsData: ModelsData = {
  summary: {
    ready: 4,
    syncing: 1,
    queued: 1,
    storageUsedGb: 642.8,
  },
  models: [
    {
      id: "mdl_trellis2_large",
      name: "TRELLIS2 Large",
      provider: "TRELLIS2",
      version: "v0.4.1",
      status: "ready",
      sizeGb: 158.4,
      minVramGb: 24,
      downloads: 3412,
      progress: 100,
      capabilities: ["capabilities.highDetail", "capabilities.pbr", "capabilities.multiView"],
      updatedAt: "2026-03-19T18:00:00+08:00",
    },
    {
      id: "mdl_trellis2_lite",
      name: "TRELLIS2 Lite",
      provider: "TRELLIS2",
      version: "v0.4.1",
      status: "ready",
      sizeGb: 92.6,
      minVramGb: 16,
      downloads: 1897,
      progress: 100,
      capabilities: ["capabilities.fastDraft", "capabilities.preview"],
      updatedAt: "2026-03-18T22:14:00+08:00",
    },
    {
      id: "mdl_hunyuan3d2",
      name: "HunYuan3D-2",
      provider: "Tencent",
      version: "preview-2026.03",
      status: "syncing",
      sizeGb: 211.3,
      minVramGb: 24,
      downloads: 922,
      progress: 67,
      capabilities: ["capabilities.highDetail", "capabilities.textureAware"],
      updatedAt: "2026-03-20T11:40:00+08:00",
    },
    {
      id: "mdl_hunyuan3d2_fast",
      name: "HunYuan3D-2 Fast",
      provider: "Tencent",
      version: "preview-2026.03",
      status: "queued",
      sizeGb: 126.9,
      minVramGb: 16,
      downloads: 0,
      progress: 12,
      capabilities: ["capabilities.fastDraft", "capabilities.preview"],
      updatedAt: "2026-03-20T09:08:00+08:00",
    },
    {
      id: "mdl_depthfusion",
      name: "DepthFusion Bridge",
      provider: "Cubie Labs",
      version: "v0.2.7",
      status: "ready",
      sizeGb: 31.5,
      minVramGb: 12,
      downloads: 603,
      progress: 100,
      capabilities: ["capabilities.cleanTopology", "capabilities.preview"],
      updatedAt: "2026-03-17T15:22:00+08:00",
    },
    {
      id: "mdl_uv_baker",
      name: "UV Baker Pro",
      provider: "Cubie Labs",
      version: "v1.1.0",
      status: "ready",
      sizeGb: 22.1,
      minVramGb: 10,
      downloads: 1203,
      progress: 100,
      capabilities: ["capabilities.textureAware", "capabilities.pbr"],
      updatedAt: "2026-03-16T12:10:00+08:00",
    },
  ],
};

export const apiKeysData: ApiKeysData = {
  usage: [
    { key: "requests", value: 1842000 },
    { key: "projects", value: 12 },
    { key: "spend", value: 38210 },
    { key: "errorRate", value: 0.31 },
  ],
  keys: [
    {
      id: "key_01",
      name: "Studio Rendering",
      prefix: "cub_stu_9f3a",
      createdAt: "2026-02-14T10:00:00+08:00",
      lastUsedAt: "2026-03-20T14:12:00+08:00",
      requests: 824000,
      scopes: ["tasks:read", "tasks:write", "models:read"],
      status: "active",
      owner: "studio-render",
    },
    {
      id: "key_02",
      name: "Agency Preview",
      prefix: "cub_age_1b7d",
      createdAt: "2026-02-26T09:24:00+08:00",
      lastUsedAt: "2026-03-20T13:45:00+08:00",
      requests: 483000,
      scopes: ["tasks:read", "tasks:write"],
      status: "active",
      owner: "agency-ops",
    },
    {
      id: "key_03",
      name: "SDK Sandbox",
      prefix: "cub_sdk_84de",
      createdAt: "2026-03-04T16:11:00+08:00",
      lastUsedAt: "2026-03-19T21:06:00+08:00",
      requests: 162000,
      scopes: ["tasks:read", "models:read", "keys:read"],
      status: "rotating",
      owner: "platform-dev",
    },
    {
      id: "key_04",
      name: "Archive Export",
      prefix: "cub_arc_31c2",
      createdAt: "2026-01-17T08:18:00+08:00",
      lastUsedAt: "2026-03-11T18:33:00+08:00",
      requests: 92000,
      scopes: ["tasks:read"],
      status: "paused",
      owner: "archive-bot",
    },
  ],
};

export const settingsData: SettingsData = {
  sections: [
    {
      key: "generation",
      titleKey: "settings.sections.generation.title",
      descriptionKey: "settings.sections.generation.description",
      fields: [
        {
          key: "defaultProvider",
          labelKey: "settings.fields.defaultProvider.label",
          descriptionKey: "settings.fields.defaultProvider.description",
          type: "select",
          value: "trellis2-large",
          options: [
            { value: "trellis2-large", labelKey: "settings.options.trellisLarge" },
            { value: "hunyuan3d-2", labelKey: "settings.options.hunyuan" },
            { value: "trellis2-lite", labelKey: "settings.options.trellisLite" },
          ],
        },
        {
          key: "maxParallelJobs",
          labelKey: "settings.fields.maxParallelJobs.label",
          descriptionKey: "settings.fields.maxParallelJobs.description",
          type: "number",
          value: 5,
          suffix: "GPU",
        },
        {
          key: "previewRenderer",
          labelKey: "settings.fields.previewRenderer.label",
          descriptionKey: "settings.fields.previewRenderer.description",
          type: "toggle",
          value: true,
        },
        {
          key: "completionWebhook",
          labelKey: "settings.fields.completionWebhook.label",
          descriptionKey: "settings.fields.completionWebhook.description",
          type: "text",
          value: "https://cubie3d.example.com/hooks/render-finished",
        },
      ],
    },
    {
      key: "storage",
      titleKey: "settings.sections.storage.title",
      descriptionKey: "settings.sections.storage.description",
      fields: [
        {
          key: "artifactBackend",
          labelKey: "settings.fields.artifactBackend.label",
          descriptionKey: "settings.fields.artifactBackend.description",
          type: "select",
          value: "minio",
          options: [
            { value: "minio", labelKey: "settings.options.minio" },
            { value: "local", labelKey: "settings.options.local" },
          ],
        },
        {
          key: "retentionDays",
          labelKey: "settings.fields.retentionDays.label",
          descriptionKey: "settings.fields.retentionDays.description",
          type: "number",
          value: 30,
          suffix: "days",
        },
        {
          key: "signedUrls",
          labelKey: "settings.fields.signedUrls.label",
          descriptionKey: "settings.fields.signedUrls.description",
          type: "toggle",
          value: true,
        },
        {
          key: "artifactPrefix",
          labelKey: "settings.fields.artifactPrefix.label",
          descriptionKey: "settings.fields.artifactPrefix.description",
          type: "text",
          value: "s3://artifacts/prod/",
        },
      ],
    },
    {
      key: "traffic",
      titleKey: "settings.sections.traffic.title",
      descriptionKey: "settings.sections.traffic.description",
      fields: [
        {
          key: "rateLimitPerMin",
          labelKey: "settings.fields.rateLimitPerMin.label",
          descriptionKey: "settings.fields.rateLimitPerMin.description",
          type: "number",
          value: 180,
          suffix: "rpm",
        },
        {
          key: "concurrencyBurst",
          labelKey: "settings.fields.concurrencyBurst.label",
          descriptionKey: "settings.fields.concurrencyBurst.description",
          type: "number",
          value: 16,
          suffix: "jobs",
        },
        {
          key: "priorityQueue",
          labelKey: "settings.fields.priorityQueue.label",
          descriptionKey: "settings.fields.priorityQueue.description",
          type: "toggle",
          value: true,
        },
        {
          key: "allowedOrigins",
          labelKey: "settings.fields.allowedOrigins.label",
          descriptionKey: "settings.fields.allowedOrigins.description",
          type: "text",
          value: "https://admin.cubie3d.com, https://studio.cubie3d.com",
        },
      ],
    },
  ],
};
