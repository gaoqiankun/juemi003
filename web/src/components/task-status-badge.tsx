import { STATUS_ICON, getVisualStatus, formatTaskStatus } from "@/lib/format";
import type { TaskRecord } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

export function TaskStatusBadge({ task }: { task: TaskRecord }) {
  const visual = getVisualStatus(task.status);
  const Icon = STATUS_ICON[visual] || STATUS_ICON.empty;
  const variant = visual === "done"
    ? "success"
    : visual === "failed"
      ? "destructive"
      : visual === "queued"
        ? "warning"
        : "default";

  return (
    <Badge variant={variant}>
      <Icon className={visual === "processing" ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
      {formatTaskStatus(task.status)}
    </Badge>
  );
}
