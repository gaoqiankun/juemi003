import { ArrowLeft, Box, Download, Orbit, SunMedium, Upload, ZoomIn, Grid3X3 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useGen3d } from "@/app/gen3d-provider";
import { ThreeViewer, type ThreeViewerHandle } from "@/components/three-viewer";
import { TaskStatusBadge } from "@/components/task-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/use-theme";
import { buildApiUrl } from "@/lib/api";
import { formatBytes, type ViewerModelStats } from "@/lib/viewer";
import { formatTime, getTaskShortId, isActiveStatus } from "@/lib/format";
import type { ArtifactPayload, TaskRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

function readTokenColor(tokenName: string, fallbackTokenName = "--surface") {
  if (typeof window === "undefined") {
    return "";
  }

  const styles = getComputedStyle(document.documentElement);
  return styles.getPropertyValue(tokenName).trim() || styles.getPropertyValue(fallbackTokenName).trim();
}

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

function formatTriangleCount(value: number, locale: string) {
  return `${new Intl.NumberFormat(locale).format(value)} tris`;
}

export function ViewerPage() {
  const { t, i18n } = useTranslation();
  const { theme } = useTheme();
  const { taskId = "" } = useParams();
  const { config, taskMap, refreshTask, subscribeToTask } = useGen3d();
  const viewerRef = useRef<ThreeViewerHandle | null>(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [showGrid, setShowGrid] = useState(false);
  const [lightingEnabled, setLightingEnabled] = useState(true);
  const [modelStats, setModelStats] = useState<ViewerModelStats | null>(null);
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

  const viewerBackground = useMemo(() => readTokenColor("--surface-container-lowest"), [theme]);
  const gridPrimaryColor = useMemo(() => readTokenColor("--outline-variant", "--ghost-outline"), [theme]);
  const gridSecondaryColor = useMemo(() => readTokenColor("--accent-strong", "--accent"), [theme]);

  const glbArtifact = getArtifactForType(task, "glb");
  const objArtifact = getArtifactForType(task, "obj");
  const glbFileName = getArtifactFileName(glbArtifact, task, "glb");
  const objFileName = getArtifactFileName(objArtifact, task, "obj");
  const glbUrl = getArtifactUrl(task, config.baseUrl, glbArtifact, "glb");
  const objUrl = getArtifactUrl(task, config.baseUrl, objArtifact, "obj");
  const displayFileName = glbFileName || `${getTaskShortId(taskId).toUpperCase() || "MODEL"}.glb`;
  const displayTaskId = task?.taskId || taskId || "--";
  const shortTaskId = getTaskShortId(displayTaskId).toUpperCase();
  const polygonLabel = modelStats?.triangleCount
    ? formatTriangleCount(modelStats.triangleCount, locale)
    : "--";
  const fileSizeLabel = glbArtifact?.size_bytes
    ? formatBytes(glbArtifact.size_bytes)
    : objArtifact?.size_bytes
      ? formatBytes(objArtifact.size_bytes)
      : "--";
  const viewerMessage = !task
    ? t("user.viewer.emptyCopy")
    : task.status === "succeeded"
      ? t("user.viewer.loadingModel")
      : task.note || task.statusLabel || t("user.viewer.emptyCopy");
  const toolbarButtonClassName = (active = false) => cn(
    "inline-flex h-11 w-11 items-center justify-center rounded-full border text-sm transition-all duration-200",
    active
      ? "border-[color:color-mix(in_srgb,var(--accent)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_14%,transparent)] text-accent-strong shadow-float"
      : "border-transparent bg-transparent text-text-secondary hover:border-outline hover:bg-surface-container-highest hover:text-text-primary",
  );

  return (
    <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem] xl:min-h-[calc(100vh-7.5rem)]">
      <div className="relative min-h-[38rem] overflow-hidden rounded-[30px] border border-outline bg-[image:var(--page-gradient)] bg-surface-container-lowest shadow-soft">
        <div className="absolute inset-0">
          <ThreeViewer
            ref={viewerRef}
            url={glbUrl || undefined}
            message={viewerMessage}
            baseUrl={config.baseUrl}
            token={config.token}
            background={viewerBackground}
            autoRotate={autoRotate}
            showGrid={showGrid}
            lightingEnabled={lightingEnabled}
            gridPrimaryColor={gridPrimaryColor}
            gridSecondaryColor={gridSecondaryColor}
            onModelStatsChange={setModelStats}
            className="!rounded-none !bg-transparent"
          />
        </div>

        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between gap-3 p-5">
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

        <div className="pointer-events-none absolute bottom-6 left-1/2 z-10 -translate-x-1/2">
          <div className="pointer-events-auto flex items-center gap-1 rounded-full border border-outline bg-surface-glass p-1 shadow-float backdrop-blur-xl">
            <button
              type="button"
              className={toolbarButtonClassName(autoRotate)}
              aria-label={t("user.viewer.toolbar.orbit")}
              title={t("user.viewer.toolbar.orbit")}
              onClick={() => setAutoRotate((current) => !current)}
            >
              <Orbit className="h-4 w-4" />
            </button>
            <button
              type="button"
              className={toolbarButtonClassName(false)}
              aria-label={t("user.viewer.toolbar.zoomIn")}
              title={t("user.viewer.toolbar.zoomIn")}
              onClick={() => viewerRef.current?.zoomIn()}
            >
              <ZoomIn className="h-4 w-4" />
            </button>
            <div className="mx-1 h-6 w-px bg-outline" />
            <button
              type="button"
              className={toolbarButtonClassName(showGrid)}
              aria-label={t("user.viewer.toolbar.grid")}
              title={t("user.viewer.toolbar.grid")}
              onClick={() => setShowGrid((current) => !current)}
            >
              <Grid3X3 className="h-4 w-4" />
            </button>
            <button
              type="button"
              className={toolbarButtonClassName(lightingEnabled)}
              aria-label={t("user.viewer.toolbar.light")}
              title={t("user.viewer.toolbar.light")}
              onClick={() => setLightingEnabled((current) => !current)}
            >
              <SunMedium className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      <aside className="flex w-full flex-col overflow-hidden rounded-[30px] border border-outline bg-surface-container-low shadow-soft xl:w-80">
        <div className="flex flex-1 flex-col p-6">
          <div className="space-y-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
              {t("user.viewer.identityLabel")}
            </div>
            <div className="text-[1.15rem] font-semibold tracking-[-0.03em] text-text-primary">
              {displayFileName}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <code className="rounded-lg border border-[color:color-mix(in_srgb,var(--accent)_18%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_10%,transparent)] px-3 py-1.5 font-mono text-xs text-accent-strong">
                {displayTaskId}
              </code>
              {task ? <TaskStatusBadge task={task} compact /> : null}
            </div>
          </div>

          <div className="mt-8 space-y-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
              {t("user.viewer.attributesLabel")}
            </div>
            <ViewerMetaRow label={t("user.viewer.details.polygons")} value={polygonLabel} />
            <ViewerMetaRow label={t("user.viewer.details.fileSize")} value={fileSizeLabel} />
            <ViewerMetaRow label={t("user.viewer.details.updated")} value={task ? formatTime(task.updatedAt || task.createdAt) : "--"} />
          </div>

          <div className="mt-8 space-y-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
              {t("user.viewer.exportsLabel")}
            </div>

            <Button asChild className="h-12 w-full justify-between rounded-xl px-4">
              <a
                href={glbUrl || "#"}
                target="_blank"
                rel="noreferrer"
                download={glbFileName || "model.glb"}
                className={!glbUrl ? "pointer-events-none opacity-50" : undefined}
              >
                <span>{t("user.viewer.actions.downloadGlb")}</span>
                <Download className="h-4 w-4" />
              </a>
            </Button>

            {objUrl ? (
              <Button asChild variant="secondary" className="h-12 w-full justify-between rounded-xl px-4">
                <a
                  href={objUrl}
                  target="_blank"
                  rel="noreferrer"
                  download={objFileName || "model.obj"}
                >
                  <span>{t("user.viewer.actions.exportObj")}</span>
                  <Box className="h-4 w-4" />
                </a>
              </Button>
            ) : (
              <Button variant="secondary" className="h-12 w-full justify-between rounded-xl px-4" disabled>
                <span>{t("user.viewer.actions.exportObj")}</span>
                <Box className="h-4 w-4" />
              </Button>
            )}
          </div>

          <div className="mt-auto pt-8">
            <Button
              className="h-12 w-full justify-center gap-3 rounded-xl text-[12px] font-semibold uppercase tracking-[0.16em]"
              onClick={() => toast(t("user.viewer.actions.comingSoon"))}
            >
              <Upload className="h-4 w-4" />
              {t("user.viewer.actions.exportEngine")}
            </Button>
          </div>
        </div>
      </aside>
    </section>
  );
}

function ViewerMetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-[14px] border border-outline bg-surface-container-lowest px-4 py-4 transition-colors hover:bg-surface-container-high">
      <span className="text-sm text-text-secondary">{label}</span>
      <span className="font-mono text-sm font-medium text-text-primary">{value}</span>
    </div>
  );
}
