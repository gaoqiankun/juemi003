import { cn } from "@/lib/utils";
import { getVisualStatus } from "@/lib/format";
import type { TaskRecord } from "@/lib/types";

function getStatusMeta(task: TaskRecord) {
  const visual = getVisualStatus(task.status);
  if (visual === "done") {
    return {
      label: "已完成",
      badge: "border-[#14532d] bg-[rgba(22,163,74,0.12)] text-[#16a34a]",
      dot: "bg-[#16a34a]",
    };
  }
  if (visual === "failed") {
    return {
      label: "失败",
      badge: "border-[#7f1d1d] bg-[rgba(220,38,38,0.12)] text-[#dc2626]",
      dot: "bg-[#dc2626]",
    };
  }
  return {
    label: "生成中",
    badge: "border-[#713f12] bg-[rgba(202,138,4,0.12)] text-[#ca8a04]",
    dot: "bg-[#ca8a04]",
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
      {showProgressText ? <span className="text-[#888888]">{Math.round(task.progress || 0)}%</span> : null}
    </div>
  );
}
