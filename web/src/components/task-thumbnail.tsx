import { Box, LoaderCircle, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useGen3d } from "@/app/gen3d-provider";
import { fetchAuthorizedBlobUrl } from "@/lib/api";
import type { TaskRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

function isActiveTask(task: TaskRecord) {
  return task.status !== "succeeded" && task.status !== "failed" && task.status !== "cancelled";
}

export function TaskThumbnail({
  task,
  className,
  variant = "default",
}: {
  task: TaskRecord;
  className?: string;
  variant?: "default" | "gallery" | "recent";
}) {
  const { config } = useGen3d();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [previewArtifactUrl, setPreviewArtifactUrl] = useState("");
  const [previewArtifactState, setPreviewArtifactState] = useState<"idle" | "loading" | "ready" | "failed">("idle");
  const [isVisible, setIsVisible] = useState(variant === "default");
  const usesArtifactPreview = variant === "gallery" || variant === "recent";
  const canFetchArtifactPreview = usesArtifactPreview && task.status === "succeeded" && Boolean(config.baseUrl) && Boolean(config.token);

  useEffect(() => {
    if (variant === "default") {
      setIsVisible(true);
      return;
    }
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "240px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [variant, task.taskId]);

  useEffect(() => {
    if (!canFetchArtifactPreview || !isVisible) {
      setPreviewArtifactState("idle");
      setPreviewArtifactUrl((previous) => {
        if (previous) {
          URL.revokeObjectURL(previous);
        }
        return "";
      });
      return;
    }

    const controller = new AbortController();
    let objectUrl = "";

    setPreviewArtifactUrl((previous) => {
      if (previous) {
        URL.revokeObjectURL(previous);
      }
      return "";
    });
    setPreviewArtifactState("loading");
    fetchAuthorizedBlobUrl(
      { baseUrl: config.baseUrl, token: config.token },
      `/v1/tasks/${encodeURIComponent(task.taskId)}/artifacts/preview.png`,
      controller.signal,
    )
      .then((url) => {
        objectUrl = url;
        setPreviewArtifactUrl((previous) => {
          if (previous) {
            URL.revokeObjectURL(previous);
          }
          return url;
        });
        setPreviewArtifactState("ready");
      })
      .catch(() => {
        if (controller.signal.aborted) {
          return;
        }
        setPreviewArtifactUrl((previous) => {
          if (previous) {
            URL.revokeObjectURL(previous);
          }
          return "";
        });
        setPreviewArtifactState("failed");
      });

    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [canFetchArtifactPreview, config.baseUrl, config.token, isVisible, task.taskId]);

  const isLoading = !usesArtifactPreview && (task.thumbnailState === "loading" || isActiveTask(task));
  const isFailed = !usesArtifactPreview && (task.status === "failed" || task.status === "cancelled");
  const renderedThumbnail = usesArtifactPreview
    ? previewArtifactState === "ready"
      ? previewArtifactUrl
      : ""
    : task.status === "succeeded"
      ? task.thumbnailUrl
      : "";
  const showArtifactPlaceholder = usesArtifactPreview && !renderedThumbnail;

  return (
    <div ref={containerRef} className={cn("relative aspect-square overflow-hidden rounded-[8px] bg-[#111111]", className)}>
      {renderedThumbnail ? (
        <img src={renderedThumbnail} alt="模型缩略图" className="absolute inset-0 size-full object-cover" />
      ) : null}

      {!usesArtifactPreview && !renderedThumbnail && !isLoading && !isFailed && task.previewDataUrl ? (
        <img src={task.previewDataUrl} alt="上传图片" className="absolute inset-0 size-full object-cover" />
      ) : null}

      {isLoading ? (
        <div className="absolute inset-0 flex items-center justify-center bg-[#111111]">
          <LoaderCircle className="h-6 w-6 animate-spin text-white/72" />
        </div>
      ) : null}

      {isFailed ? (
        <div className="absolute inset-0 flex items-center justify-center bg-[#111111]">
          <X className="h-8 w-8 text-white/46" />
        </div>
      ) : null}

      {showArtifactPlaceholder ? (
        <div className="absolute inset-0 flex items-center justify-center bg-[#111111]">
          <Box className="h-10 w-10 text-white/24" />
        </div>
      ) : null}
    </div>
  );
}
