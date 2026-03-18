import { ImagePlus, Sparkles, UploadCloud, X } from "lucide-react";

import { Button } from "@/components/ui/button";

export function UploadDropzone({
  previewUrl,
  fileName,
  onFileSelect,
  onClear,
  disabled,
}: {
  previewUrl?: string;
  fileName?: string;
  onFileSelect: (file: File | null) => void;
  onClear: () => void;
  disabled?: boolean;
}) {
  return (
    <label
      className="group relative block cursor-pointer overflow-hidden rounded-[32px] border border-white/10 bg-[linear-gradient(145deg,rgba(14,22,38,0.96),rgba(5,8,18,0.92))] p-6 transition hover:border-cyan-400/30 hover:bg-[linear-gradient(145deg,rgba(17,27,46,0.98),rgba(6,10,18,0.96))]"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        onFileSelect(event.dataTransfer.files?.[0] || null);
      }}
    >
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="hidden"
        disabled={disabled}
        onChange={(event) => onFileSelect(event.target.files?.[0] || null)}
      />

      <div className="grid gap-6 md:grid-cols-[1.04fr_0.96fr] md:items-center">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1.5 text-xs uppercase tracking-[0.22em] text-cyan-100">
            <Sparkles className="h-3.5 w-3.5" />
            Upload Input
          </div>
          <h2 className="mt-4 font-display text-3xl font-semibold tracking-[-0.04em] text-white md:text-4xl">
            把输入图像直接拖进来。
          </h2>
          <p className="mt-4 max-w-xl text-sm leading-7 text-slate-300 md:text-base">
            上传后会自动走 /v1/upload，再创建 /v1/tasks。整个主屏只保留一个当前任务视图，用于高密度关注生成过程。
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button type="button" variant="secondary" disabled={disabled}>
              <UploadCloud className="h-4 w-4" />
              选择图片
            </Button>
            <Button type="button" variant="outline" onClick={(event) => {
              event.preventDefault();
              onClear();
            }} disabled={!previewUrl || disabled}>
              <X className="h-4 w-4" />
              清除
            </Button>
          </div>
        </div>

        <div className="relative overflow-hidden rounded-[28px] border border-white/10 bg-slate-950 min-h-[260px]">
          {previewUrl ? (
            <img src={previewUrl} alt="input preview" className="size-full object-cover" />
          ) : (
            <div className="flex h-full min-h-[260px] flex-col items-center justify-center gap-4 px-8 text-center">
              <ImagePlus className="h-12 w-12 text-slate-300" />
              <div>
                <div className="font-display text-lg font-semibold text-white">当前还没选图</div>
                <div className="mt-2 text-sm leading-6 text-slate-400">建议主体明确、背景简单，优先 1:1 或近似方图。</div>
              </div>
            </div>
          )}
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-slate-950 via-slate-950/70 to-transparent px-4 py-4 text-sm text-slate-200">
            {fileName || "等待输入图片"}
          </div>
        </div>
      </div>
    </label>
  );
}
