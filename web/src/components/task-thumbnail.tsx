import { Box, ImagePlus } from "lucide-react";

import { formatTaskStatus, getTaskShortId } from "@/lib/format";
import type { TaskRecord } from "@/lib/types";

export function TaskThumbnail({ task, compact = false }: { task: TaskRecord; compact?: boolean }) {
  const heightClass = compact ? "h-44" : "h-56";

  if (task.thumbnailUrl) {
    return (
      <div className={`relative overflow-hidden rounded-[24px] border border-white/10 bg-slate-950 ${heightClass}`}>
        <img src={task.thumbnailUrl} alt={`${task.taskId} 3D thumbnail`} className="size-full object-cover" />
        <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 bg-gradient-to-t from-slate-950 via-slate-950/70 to-transparent px-4 py-4 text-xs uppercase tracking-[0.18em] text-slate-200">
          <span>3D Preview</span>
          <span>{task.model}</span>
        </div>
      </div>
    );
  }

  if (task.previewDataUrl) {
    return (
      <div className={`relative overflow-hidden rounded-[24px] border border-white/10 bg-slate-950 ${heightClass}`}>
        <img src={task.previewDataUrl} alt={`${task.taskId} input preview`} className="size-full object-cover" />
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-slate-950 via-slate-950/70 to-transparent px-4 py-4 text-xs uppercase tracking-[0.18em] text-slate-200">
          Input Preview
        </div>
      </div>
    );
  }

  return (
    <div className={`relative overflow-hidden rounded-[24px] border border-white/10 bg-[radial-gradient(circle_at_top,rgba(56,189,248,0.18),transparent_40%),linear-gradient(180deg,rgba(10,16,30,1),rgba(5,8,18,1))] ${heightClass}`}>
      <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.05),transparent_40%,rgba(34,197,94,0.08))]" />
      <div className="relative flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
        {task.status === "succeeded" ? (
          <Box className="h-12 w-12 text-cyan-200" />
        ) : (
          <ImagePlus className="h-12 w-12 text-slate-300" />
        )}
        <div>
          <div className="font-display text-base font-semibold text-white">{formatTaskStatus(task.status)}</div>
          <div className="mt-2 text-sm leading-6 text-slate-400">
            {task.status === "succeeded"
              ? task.thumbnailState === "loading"
                ? "正在生成 3D 缩略图…"
                : "可在详情侧栏查看完整模型"
              : "等待后端产物完成后展示 3D 缩略图"}
          </div>
        </div>
      </div>
      <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 border-t border-white/10 bg-slate-950/70 px-4 py-3 text-xs uppercase tracking-[0.18em] text-slate-300">
        <span>{getTaskShortId(task.taskId)}</span>
        <span>{task.model}</span>
      </div>
    </div>
  );
}
