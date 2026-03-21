import { ArrowLeft, Clock, Download, FileBox, Layers, Trash2, Triangle } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useGen3d } from "@/app/gen3d-provider";
import { ModelViewport } from "@/components/model-viewport";
import { TaskStatusBadge } from "@/components/task-status-badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { buildApiUrl } from "@/lib/api";
import { formatRelativeTime, getTaskShortId, isActiveStatus } from "@/lib/format";
import { formatBytes, type ViewerModelStats } from "@/lib/viewer";
import type { ArtifactPayload, TaskRecord } from "@/lib/types";


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

const FORMAT_OPTIONS: {
  value: ExportFormat;
  labelKey: string;
}[] = [
  {
    value: "glb",
    labelKey: "user.viewer.exportFormats.glb.label",
  },
  {
    value: "obj",
    labelKey: "user.viewer.exportFormats.obj.label",
  },
];

export function ViewerPage() {
  const { t, i18n } = useTranslation();
  const { taskId = "" } = useParams();
  const navigate = useNavigate();
  const { config, taskMap, refreshTask, subscribeToTask, deleteTask } = useGen3d();
  const [modelStats, setModelStats] = useState<ViewerModelStats | null>(null);
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>("glb");
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
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
  const updatedLabel = task
    ? formatRelativeTime(task.updatedAt || task.createdAt, i18n.resolvedLanguage)
    : "--";

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
  const canDelete = Boolean(task?.taskId) && !isDeleting;

  const handleDeleteConfirm = () => {
    if (!task?.taskId || isDeleting) {
      return;
    }
    setIsDeleting(true);
    deleteTask(task.taskId)
      .then(() => {
        setIsDeleteOpen(false);
        navigate("/gallery", { replace: true });
      })
      .catch(() => undefined)
      .finally(() => setIsDeleting(false));
  };

  const sidebarPanel = (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-outline bg-surface-glass shadow-soft backdrop-blur-xl">
      <div className="flex flex-1 flex-col gap-7 overflow-y-auto p-6">
        <div className="space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
            {t("user.viewer.breadcrumb")}
          </div>
          <h1 className="text-xl font-bold leading-tight tracking-[-0.02em] text-text-primary">
            {shortTaskId}
          </h1>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {task ? <TaskStatusBadge task={task} compact /> : null}
          </div>
        </div>

        {task?.previewDataUrl ? (
          <div className="overflow-hidden rounded-xl border border-outline bg-surface-container-lowest">
            <img
              src={task.previewDataUrl}
              alt=""
              className="h-40 w-full object-cover"
            />
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-3">
          <StatCard icon={<Triangle className="h-4 w-4" />} label={t("user.viewer.details.polygons")} value={polygonCount} />
          <StatCard icon={<FileBox className="h-4 w-4" />} label={t("user.viewer.details.fileSize")} value={fileSizeLabel} />
          <StatCard icon={<Layers className="h-4 w-4" />} label={t("user.viewer.details.meshes")} value={meshCount} />
          <StatCard icon={<Clock className="h-4 w-4" />} label={t("user.viewer.details.updated")} value={updatedLabel} />
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
              {t("user.viewer.exportsLabel")}
            </div>
            <div className="w-[11.25rem]">
              <Select value={selectedFormat} onValueChange={(next) => setSelectedFormat(next as ExportFormat)}>
                <SelectTrigger className="h-10 rounded-xl border-outline bg-surface-container-low text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FORMAT_OPTIONS.map((fmt) => {
                    const isAvailable = fmt.value === "glb" ? Boolean(glbUrl) : Boolean(objUrl);
                    return (
                      <SelectItem key={fmt.value} value={fmt.value} disabled={!isAvailable}>
                        {t(fmt.labelKey)}
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

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
            disabled={!canDelete}
            className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-[color:color-mix(in_srgb,var(--danger)_24%,transparent)] bg-[color:color-mix(in_srgb,var(--danger)_10%,transparent)] px-4 text-sm font-medium text-danger-text transition hover:bg-[color:color-mix(in_srgb,var(--danger)_16%,transparent)] disabled:cursor-not-allowed disabled:opacity-55"
            onClick={() => setIsDeleteOpen(true)}
          >
            <Trash2 className="h-4 w-4" />
            {t("user.viewer.deleteButton")}
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <section className="relative -mx-4 -my-6 min-h-[calc(100vh-6rem)] overflow-hidden md:-mx-6">
      <div className="absolute inset-0 overflow-hidden bg-surface-container-lowest">
        <ModelViewport
          url={glbUrl || undefined}
          message={viewerMessage}
          baseUrl={config.baseUrl}
          token={config.token}
          className="absolute inset-0"
          onModelStatsChange={setModelStats}
          topOverlay={(
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
          )}
        />
      </div>

      <div className="pointer-events-none relative z-10 hidden min-h-[calc(100vh-6rem)] md:block">
        <aside className="pointer-events-auto absolute bottom-4 right-4 top-4 w-[20rem] xl:w-[22rem]">
          {sidebarPanel}
        </aside>
      </div>

      <div className="pointer-events-auto relative z-10 mt-3 grid gap-3 px-3 pb-3 md:hidden">
        {sidebarPanel}
      </div>

      <AlertDialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("user.viewer.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("user.viewer.deleteDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button variant="outline" disabled={isDeleting}>
                {t("user.viewer.cancelButton")}
              </Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button variant="destructive" disabled={!canDelete} onClick={handleDeleteConfirm}>
                {t("user.viewer.deleteButton")}
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-2xl border border-outline bg-surface-container-lowest p-3">
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted">{icon}</span>
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">{label}</div>
      </div>
      <div>
        <div className="mt-0.5 text-base font-bold tracking-tight text-text-primary">{value}</div>
      </div>
    </div>
  );
}
