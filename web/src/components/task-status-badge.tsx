import { cn } from "@/lib/utils";
import { getVisualStatus } from "@/lib/format";
import type { TaskRecord } from "@/lib/types";

function getStatusMeta(task: TaskRecord) {
  const visual = getVisualStatus(task.status);
  if (visual === "done") {
    return {
      label: "已完成",
      badge: "border-[color:color-mix(in_srgb,var(--success)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--success)_12%,var(--surface-container-low))] text-success-text",
      dot: "bg-success-text",
    };
  }
  if (visual === "failed") {
    return {
      label: "失败",
      badge: "border-[color:color-mix(in_srgb,var(--danger)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--danger)_12%,var(--surface-container-low))] text-danger-text",
      dot: "bg-danger-text",
    };
  }
  return {
    label: "生成中",
    badge: "border-[color:color-mix(in_srgb,var(--warning)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--warning)_12%,var(--surface-container-low))] text-warning-text",
    dot: "bg-warning-text",
  };
}

export function TaskStatusBadge({
  task,
  compact = false,
  className,
  showProgress = false,
}: {
  task: TaskRecord;
  compact?: boolean;
  className?: string;
  showProgress?: boolean;
}) {
  const status = getStatusMeta(task);
  const showProgressText = showProgress && getVisualStatus(task.status) === "processing";

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-full border font-medium",
        compact ? "h-6 px-2.5 text-[11px]" : "h-7 px-3 text-[12px]",
        status.badge,
        className,
      )}
    >
      <span className={cn("rounded-full", compact ? "h-1.5 w-1.5" : "h-2 w-2", status.dot)} />
      <span>{status.label}</span>
      {showProgressText ? <span className="text-text-muted">{Math.round(task.progress || 0)}%</span> : null}
    </div>
  );
}
