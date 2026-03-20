export type UserGenerationStatus = "processing" | "completed" | "failed";

export interface GenerationRecord {
  id: string;
  titleKey: string;
  promptKey: string;
  status: UserGenerationStatus;
  createdAt: string;
  updatedAt: string;
  progress: number;
  quality: "draft" | "production" | "ultra";
  format: "glb" | "obj" | "usdz";
  fileSizeMb: number;
  polygonCount: number;
  downloadFormats: string[];
}

export interface GenerateData {
  qualityOptions: Array<{ value: GenerationRecord["quality"]; labelKey: string }>;
  formatOptions: Array<{ value: GenerationRecord["format"]; labelKey: string }>;
  featuredTask: GenerationRecord;
  progressSteps: Array<{ key: string; progress: number }>;
}

export interface GenerationsData {
  filters: Array<{ value: "all" | UserGenerationStatus; labelKey: string }>;
  records: GenerationRecord[];
}

export interface ViewerData {
  activeTask: GenerationRecord;
  detailItems: Array<{ labelKey: string; value: string }>;
}

export interface SetupData {
  defaultServerUrl: string;
  helperKey: string;
}

export const generationRecords: GenerationRecord[] = [
  {
    id: "gen_8de14a11",
    titleKey: "user.mockTitles.sneaker",
    promptKey: "user.mockPrompts.sneaker",
    status: "processing",
    createdAt: "2026-03-20T16:10:00+08:00",
    updatedAt: "2026-03-20T16:18:00+08:00",
    progress: 68,
    quality: "production",
    format: "glb",
    fileSizeMb: 42.8,
    polygonCount: 184000,
    downloadFormats: ["glb", "obj", "usdz"],
  },
  {
    id: "gen_04f92c7b",
    titleKey: "user.mockTitles.headset",
    promptKey: "user.mockPrompts.headset",
    status: "completed",
    createdAt: "2026-03-20T14:52:00+08:00",
    updatedAt: "2026-03-20T15:03:00+08:00",
    progress: 100,
    quality: "ultra",
    format: "usdz",
    fileSizeMb: 89.1,
    polygonCount: 326400,
    downloadFormats: ["glb", "obj", "usdz"],
  },
  {
    id: "gen_6caefcd2",
    titleKey: "user.mockTitles.lamp",
    promptKey: "user.mockPrompts.lamp",
    status: "completed",
    createdAt: "2026-03-20T12:34:00+08:00",
    updatedAt: "2026-03-20T12:44:00+08:00",
    progress: 100,
    quality: "production",
    format: "glb",
    fileSizeMb: 55.6,
    polygonCount: 218300,
    downloadFormats: ["glb", "obj"],
  },
  {
    id: "gen_c31d02ff",
    titleKey: "user.mockTitles.chair",
    promptKey: "user.mockPrompts.chair",
    status: "completed",
    createdAt: "2026-03-19T20:18:00+08:00",
    updatedAt: "2026-03-19T20:31:00+08:00",
    progress: 100,
    quality: "draft",
    format: "obj",
    fileSizeMb: 31.2,
    polygonCount: 104500,
    downloadFormats: ["glb", "obj"],
  },
];

export const generateData: GenerateData = {
  qualityOptions: [
    { value: "draft", labelKey: "user.generate.options.qualityDraft" },
    { value: "production", labelKey: "user.generate.options.qualityProduction" },
    { value: "ultra", labelKey: "user.generate.options.qualityUltra" },
  ],
  formatOptions: [
    { value: "glb", labelKey: "user.generate.options.formatGlb" },
    { value: "obj", labelKey: "user.generate.options.formatObj" },
    { value: "usdz", labelKey: "user.generate.options.formatUsdz" },
  ],
  featuredTask: generationRecords[1],
  progressSteps: [
    { key: "user.generate.steps.uploaded", progress: 100 },
    { key: "user.generate.steps.geometry", progress: 82 },
    { key: "user.generate.steps.materials", progress: 64 },
    { key: "user.generate.steps.packaging", progress: 28 },
  ],
};

export const generationsData: GenerationsData = {
  filters: [
    { value: "all", labelKey: "user.generations.filters.all" },
    { value: "processing", labelKey: "user.generations.filters.processing" },
    { value: "completed", labelKey: "user.generations.filters.completed" },
    { value: "failed", labelKey: "user.generations.filters.failed" },
  ],
  records: generationRecords,
};

export function resolveViewerData(taskId: string): ViewerData {
  const activeTask = generationRecords.find((item) => item.id === taskId) ?? {
    ...generationRecords[0],
    id: taskId,
  };

  return {
    activeTask,
    detailItems: [
      { labelKey: "user.viewer.details.quality", value: activeTask.quality },
      { labelKey: "user.viewer.details.format", value: activeTask.format.toUpperCase() },
      { labelKey: "user.viewer.details.polygons", value: `${activeTask.polygonCount.toLocaleString()} tris` },
      { labelKey: "user.viewer.details.fileSize", value: `${activeTask.fileSizeMb.toFixed(1)} MB` },
    ],
  };
}

export const setupData: SetupData = {
  defaultServerUrl: "http://127.0.0.1:19001",
  helperKey: "user.setup.helper",
};
