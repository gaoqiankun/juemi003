import { ArrowLeft, Clock, Download, FileBox, Share2, Layers, Triangle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useGen3d } from "@/app/gen3d-provider";
import { ModelViewport } from "@/components/model-viewport";
import { TaskStatusBadge } from "@/components/task-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buildApiUrl } from "@/lib/api";
import { formatBytes, type ViewerModelStats } from "@/lib/viewer";
import { formatTime, getTaskShortId, isActiveStatus } from "@/lib/format";
import type { ArtifactPayload, TaskRecord } from "@/lib/types";
import { cn } from "@/lib/utils";


function getArtifactForType(task: TaskRecord | null, type: string) {
  if (!task) {
    return null;
  }
  if (type === "glb") {
    return task.artifacts.find((artifact) => artifact.type === "glb") || task.artifacts[0] || null;
  }
  return task.artifacts.find((artifact) => artifact.type === type) || null;
}

function getArtifactFileName(artifact: ArtifactPayload | null, task: TaskRecord | null, type: string) {
  const sourceUrl = artifact?.url || (type === "glb" ? task?.rawArtifactUrl || task?.resolvedArtifactUrl || "" : "");
  if (!sourceUrl) {
    return "";
  }
  try {
    const parsed = new URL(sourceUrl, window.location.origin);
    return decodeURIComponent(parsed.pathname.split("/").filter(Boolean).pop() || "");
  } catch {
    return "";
  }
}

function getArtifactUrl(task: TaskRecord | null, baseUrl: string, artifact: ArtifactPayload | null, type: string) {
  const fallbackUrl = type === "glb" ? task?.resolvedArtifactUrl || task?.rawArtifactUrl || "" : "";
  const sourceUrl = String(artifact?.url || fallbackUrl || "").trim();
  if (!sourceUrl) {
    return "";
  }
  if (/^https?:\/\//i.test(sourceUrl)) {
    return sourceUrl;
  }
  return baseUrl ? buildApiUrl(baseUrl, sourceUrl) : sourceUrl;
}

type ExportFormat = "glb" | "obj";

const FORMAT_OPTIONS: { value: ExportFormat; label: string; description: string }[] = [
  { value: "glb", label: "Binary glTF (.glb)", description: "Best for Web & AR" },
  { value: "obj", label: "Wavefront (.obj)", description: "Best for Desktop DCCs" },
];

export function ViewerPage() {
  const { t, i18n } = useTranslation();
  const { taskId = "" } = useParams();
  const { config, taskMap, refreshTask, subscribeToTask } = useGen3d();
  const [modelStats, setModelStats] = useState<ViewerModelStats | null>(null);
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>("glb");
  const locale = i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en-US";
  const task = taskId ? taskMap[taskId] || null : null;

  useEffect(() => {
    if (!taskId) {
      return;
    }
    refreshTask(taskId, { silent: true }).catch(() => undefined);
  }, [refreshTask, taskId]);

  useEffect(() => {
    if (!taskId || !task || !isActiveStatus(task.status)) {
      return;
    }
    subscribeToTask(taskId, true).catch(() => undefined);
  }, [subscribeToTask, task?.status, taskId]);

  const glbArtifact = getArtifactForType(task, "glb");
  const objArtifact = getArtifactForType(task, "obj");
  const glbFileName = getArtifactFileName(glbArtifact, task, "glb");
  const objFileName = getArtifactFileName(objArtifact, task, "obj");
  const glbUrl = getArtifactUrl(task, config.baseUrl, glbArtifact, "glb");
  const objUrl = getArtifactUrl(task, config.baseUrl, objArtifact, "obj");
  const displayFileName = glbFileName || `${getTaskShortId(taskId).toUpperCase() || "MODEL"}.glb`;
  const shortTaskId = getTaskShortId(task?.taskId || taskId).toUpperCase();

  const polygonCount = modelStats?.triangleCount
    ? new Intl.NumberFormat(locale).format(modelStats.triangleCount)
    : "--";
  const meshCount = modelStats?.meshCount
    ? String(modelStats.meshCount)
    : "--";
  const fileSizeLabel = glbArtifact?.size_bytes
    ? formatBytes(glbArtifact.size_bytes)
    : objArtifact?.size_bytes
      ? formatBytes(objArtifact.size_bytes)
      : "--";
  const updatedLabel = task ? formatTime(task.updatedAt || task.createdAt) : "--";

  const viewerMessage = !task
    ? t("user.viewer.emptyCopy")
    : task.status === "succeeded"
      ? t("user.viewer.loadingModel")
      : task.note || task.statusLabel || t("user.viewer.emptyCopy");

  const downloadUrl = selectedFormat === "glb" ? glbUrl : objUrl;
  const downloadFileName = selectedFormat === "glb"
    ? (glbFileName || "model.glb")
    : (objFileName || "model.obj");
  const canDownload = Boolean(downloadUrl);

  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem] lg:min-h-[calc(100vh-7.5rem)] xl:grid-cols-[minmax(0,1fr)_22rem]">
      {/* ── Viewer ── */}
      <ModelViewport
        url={glbUrl || undefined}
        message={viewerMessage}
        baseUrl={config.baseUrl}
        token={config.token}
        className="min-h-[38rem] rounded-[30px] border border-outline shadow-soft"
        onModelStatsChange={setModelStats}
        topOverlay={
          <div className="pointer-events-none flex items-start justify-between gap-3">
            <Link
              to="/gallery"
              className="pointer-events-auto inline-flex h-11 items-center gap-2 rounded-full border border-outline bg-surface-glass px-4 text-sm font-medium text-text-primary shadow-float backdrop-blur-xl transition hover:border-[color:color-mix(in_srgb,var(--accent)_24%,transparent)] hover:text-accent-strong"
            >
              <ArrowLeft className="h-4 w-4" />
              {t("user.viewer.backButton")}
            </Link>
            <Badge
              variant="accent"
              className="pointer-events-auto h-11 rounded-full px-4 text-[11px] font-semibold uppercase tracking-[0.16em]"
            >
              ID · {shortTaskId}
            </Badge>
          </div>
        }
      />

      {/* ── Sidebar ── */}
      <aside className="flex w-full flex-col overflow-hidden rounded-[30px] border border-outline bg-surface-container-low shadow-soft lg:w-[20rem] xl:w-[22rem]">
        <div className="flex flex-1 flex-col gap-7 overflow-y-auto p-6">
          {/* Header */}
          <div className="space-y-2">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
              {t("user.viewer.breadcrumb")}
            </div>
            <h1 className="text-xl font-bold tracking-[-0.02em] text-text-primary leading-tight">
              {displayFileName}
            </h1>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <code className="rounded-lg border border-[color:color-mix(in_srgb,var(--accent)_18%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_10%,transparent)] px-2.5 py-1 font-mono text-xs text-accent-strong">
                {shortTaskId}
              </code>
              {task ? <TaskStatusBadge task={task} compact /> : null}
            </div>
          </div>

          {/* Stats 2×2 grid */}
          <div className="grid grid-cols-2 gap-3">
            <StatCard icon={<Triangle className="h-4 w-4" />} label={t("user.viewer.details.polygons")} value={polygonCount} />
            <StatCard icon={<FileBox className="h-4 w-4" />} label={t("user.viewer.details.fileSize")} value={fileSizeLabel} />
            <StatCard icon={<Layers className="h-4 w-4" />} label={t("user.viewer.details.meshes")} value={meshCount} />
            <StatCard icon={<Clock className="h-4 w-4" />} label={t("user.viewer.details.updated")} value={updatedLabel} />
          </div>

          {/* Export options */}
          <div className="space-y-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
              {t("user.viewer.exportsLabel")}
            </div>
            <div className="space-y-2">
              {FORMAT_OPTIONS.map((fmt) => {
                const isAvailable = fmt.value === "glb" ? Boolean(glbUrl) : Boolean(objUrl);
                const isSelected = selectedFormat === fmt.value;
                return (
                  <button
                    key={fmt.value}
                    type="button"
                    disabled={!isAvailable}
                    onClick={() => setSelectedFormat(fmt.value)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-2xl border px-4 py-3.5 text-left transition-all",
                      isSelected
                        ? "border-accent bg-[color:color-mix(in_srgb,var(--accent)_8%,transparent)]"
                        : "border-outline bg-surface-container-lowest hover:bg-surface-container-high",
                      !isAvailable && "cursor-not-allowed opacity-40",
                    )}
                  >
                    <span className={cn(
                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                      isSelected ? "border-accent" : "border-text-muted",
                    )}>
                      {isSelected ? <span className="h-2.5 w-2.5 rounded-full bg-accent" /> : null}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-text-primary">{fmt.label}</span>
                      <span className="block text-xs text-text-secondary">{fmt.description}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Download button */}
          <div className="mt-auto space-y-3">
            <Button
              asChild={canDownload}
              className="h-12 w-full justify-center gap-2.5 rounded-xl text-sm font-semibold"
              disabled={!canDownload}
            >
              {canDownload ? (
                <a href={downloadUrl} target="_blank" rel="noreferrer" download={downloadFileName}>
                  <Download className="h-4 w-4" />
                  {t("user.viewer.actions.download")}
                </a>
              ) : (
                <>
                  <Download className="h-4 w-4" />
                  {t("user.viewer.actions.download")}
                </>
              )}
            </Button>

            <button
              type="button"
              className="flex w-full items-center justify-center gap-2 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary"
              onClick={() => {
                const url = window.location.href;
                navigator.clipboard.writeText(url).then(
                  () => toast(t("user.viewer.actions.linkCopied")),
                  () => toast.error(t("user.viewer.actions.linkCopyFailed")),
                );
              }}
            >
              <Share2 className="h-3.5 w-3.5" />
              {t("user.viewer.actions.shareLink")}
            </button>
          </div>
        </div>
      </aside>
    </section>
  );
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex flex-col gap-2.5 rounded-2xl border border-outline bg-surface-container-lowest p-4">
      <span className="text-text-muted">{icon}</span>
      <div>
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">{label}</div>
        <div className="mt-0.5 text-base font-bold tracking-tight text-text-primary">{value}</div>
      </div>
    </div>
  );
}
